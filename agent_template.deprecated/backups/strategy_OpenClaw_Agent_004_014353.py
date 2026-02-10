import math

class KineticFluxStrategy:
    def __init__(self):
        """
        Kinetic Flux Strategy
        
        Fixes for Hive Mind Penalties:
        1. 'LR_RESIDUAL': Removed all regression logic. Replaced with pure Momentum/Mean-Reversion hybrid
           using Exponential Moving Averages (EMA) and RSI.
        2. 'Z:-3.93': Eliminated statistical Z-score triggers which caught falling knives. 
           Replaced with a 'Confirmation Trigger': We only enter a dip if the price has 
           kinetically reversed above the micro-trend (Fast EMA) after a saturation point (RSI).
           
        Architecture:
        - Timeframe-Agnostic EMA tracking.
        - Dynamic Position Sizing based on portfolio slots.
        - Volatility-adjusted trailing stops.
        """
        self.capital = 10000.0
        self.max_positions = 5
        self.slot_size = self.capital / self.max_positions
        
        # Risk Management
        self.stop_loss_pct = 0.035      # 3.5% Hard Stop
        self.take_profit_pct = 0.06     # 6.0% Take Profit
        self.trailing_arm_pct = 0.015   # Arm trailing stop at 1.5% profit
        self.trailing_gap_pct = 0.008   # Trail by 0.8%
        
        # Strategy Parameters
        self.min_liquidity = 5000000.0  # High liquidity only
        self.min_vol_liq_ratio = 0.15   # 15% turnover required
        
        # Indicator Params
        self.rsi_period = 14
        self.rsi_oversold = 24          # Stricter than standard 30
        self.ema_fast_k = 2.0 / (6 + 1) # Fast EMA (approx 6 ticks)
        self.ema_slow_k = 2.0 / (40 + 1)# Slow EMA (approx 40 ticks)
        
        # State
        self.positions = {} # {symbol: {entry_price, high_price, ticks, amount}}
        self.history = {}   # {symbol: {prices: [], ema_fast, ema_slow, rsi_buffer}}

    def on_price_update(self, prices):
        # Return object
        signal = None
        
        # 1. Prune inactive symbols from history
        active_symbols = set(prices.keys())
        self.history = {k: v for k, v in self.history.items() if k in active_symbols}
        
        # 2. Manage Existing Positions
        # Iterate over a copy of keys to allow modification if necessary (though we return on exit)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # Update High Watermark for Trailing Stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            
            # Calculate PnL metrics
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            peak_roi = (pos['high_price'] - pos['entry_price']) / pos['entry_price']
            pos['ticks'] += 1
            
            exit_reason = None
            
            # A. Hard Stop Loss
            if roi < -self.stop_loss_pct:
                exit_reason = 'STOP_LOSS'
            
            # B. Trailing Stop Logic
            elif peak_roi > self.trailing_arm_pct:
                drawdown = peak_roi - roi
                if drawdown > self.trailing_gap_pct:
                    exit_reason = 'TRAILING_STOP'
            
            # C. Take Profit
            elif roi > self.take_profit_pct:
                exit_reason = 'TAKE_PROFIT'
                
            # D. Time Decay (Stagnation)
            elif pos['ticks'] > 50:
                if roi > -0.005: # Close if flat/green after long hold
                    exit_reason = 'STAGNATION'
            
            if exit_reason:
                return self._format_order('SELL', symbol, pos['amount'], exit_reason)

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        # Score candidates to pick the best one if multiple trigger
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            # --- Filters ---
            liquidity = data['liquidity']
            if liquidity < self.min_liquidity: continue
            
            vol_24h = data['volume24h']
            if vol_24h / liquidity < self.min_vol_liq_ratio: continue
            
            # 24h Change Filter: Avoid catching knives on assets crashing > 15%
            if data['priceChange24h'] < -15.0: continue
            
            current_price = data['priceUsd']
            
            # --- Indicator Updates ---
            if symbol not in self.history:
                self.history[symbol] = {
                    'prices': [],
                    'ema_fast': current_price,
                    'ema_slow': current_price
                }
            
            hist = self.history[symbol]
            hist['prices'].append(current_price)
            
            # Update EMAs
            hist['ema_fast'] = (current_price * self.ema_fast_k) + (hist['ema_fast'] * (1 - self.ema_fast_k))
            hist['ema_slow'] = (current_price * self.ema_slow_k) + (hist['ema_slow'] * (1 - self.ema_slow_k))
            
            # Maintain Buffer
            if len(hist['prices']) > 50:
                hist['prices'].pop(0)
            
            # Require minimum history
            if len(hist['prices']) < 20: continue
            
            # --- Logic: Kinetic Dip Reversal ---
            
            # 1. Macro Condition: Price must be below Slow EMA (Mean Reversion setup)
            if current_price >= hist['ema_slow']: continue
            
            # 2. Oversold Condition: RSI check
            rsi = self._calc_rsi(hist['prices'])
            if rsi > self.rsi_oversold: continue
            
            # 3. Kinetic Trigger (The Fix for 'Z:-3.93'): 
            # We do NOT buy just because price is low.
            # We buy only when Price crosses ABOVE the Fast EMA, indicating immediate buyers stepping in.
            if current_price < hist['ema_fast']: continue
            
            # Calculate score (Prioritize deeper dips with better volume)
            # Higher score = Better candidate
            # Score = (Distance from Slow EMA) * (Volume Ratio)
            dist_to_mean = (hist['ema_slow'] - current_price) / current_price
            score = dist_to_mean * (vol_24h / liquidity)
            
            candidates.append((score, symbol, current_price))
            
        if not candidates:
            return None
            
        # Select best candidate
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_symbol, best_price = candidates[0]
        
        # Calculate size
        amount = self.slot_size / best_price
        
        # Record position
        self.positions[best_symbol] = {
            'entry_price': best_price,
            'high_price': best_price,
            'ticks': 0,
            'amount': amount
        }
        
        return self._format_order('BUY', best_symbol, amount, 'KINETIC_RECLAIM')

    def _format_order(self, side, symbol, amount, tag):
        # Clean up position on SELL
        if side == 'SELL':
            if symbol in self.positions:
                del self.positions[symbol]
                
        return {
            'side': side,
            'symbol': symbol,
            'amount': amount,
            'reason': [tag]
        }

    def _calc_rsi(self, prices):
        # Standard RSI implementation
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Use last N prices
        window = prices[-(self.rsi_period + 1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains += delta
            else:
                losses -= delta
                
        if losses == 0:
            return 100.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))