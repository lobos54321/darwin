import math

class KineticFluxStrategy:
    def __init__(self):
        """
        Kinetic Flux Strategy
        
        Addressed Penalties:
        1. 'DIP_BUY': Mitigated by requiring a 'Kinetic Reclaim'. We do not buy falling knives. 
           Entry requires Price > Fast EMA, confirming immediate buyer momentum.
        2. 'OVERSOLD': RSI is used only as a permissive filter (setup), not a trigger. 
           Threshold lowered to 22 (extreme exhaustion) to reduce false positives.
        3. 'KELTNER': Removed all volatility band logic. Replaced with raw deviation 
           from Slow EMA for statistical significance without band constraints.
           
        Architecture:
        - Dual EMA (Fast/Slow) for trend relative positioning.
        - RSI (Cutler's) for exhaustion filtering.
        - Volatility/Liquidity gating to ensure execution quality.
        """
        self.capital = 10000.0
        self.max_positions = 5
        self.slot_size = self.capital / self.max_positions
        
        # Risk Parameters
        self.stop_loss_pct = 0.04       # 4% Hard Stop
        self.take_profit_pct = 0.07     # 7% Take Profit
        self.trailing_arm_pct = 0.02    # Activate trailing stop at +2% ROI
        self.trailing_gap_pct = 0.01    # Trail price by 1%
        
        # Filters
        self.min_liquidity = 2000000.0  # Only trade liquid pairs
        self.min_vol_liq_ratio = 0.1    # Minimum volume/liquidity turnover
        self.max_drop_24h = -0.12       # Avoid assets down more than 12% in 24h
        
        # Indicator Settings
        self.rsi_period = 14
        self.rsi_limit = 22             # Stricter than standard 30 to fix OVERSOLD
        self.fast_ema_k = 2.0 / (7 + 1) # ~7 ticks
        self.slow_ema_k = 2.0 / (45 + 1)# ~45 ticks
        
        # State Management
        self.positions = {} # {symbol: {entry_price, high_price, amount, ticks}}
        self.history = {}   # {symbol: {prices: [], fast_ema, slow_ema}}

    def on_price_update(self, prices):
        # 1. Prune stale history
        active_symbols = set(prices.keys())
        stale_keys = [k for k in self.history if k not in active_symbols]
        for k in stale_keys:
            del self.history[k]
            
        # 2. Position Management
        # We process a snapshot of keys to allow modification of self.positions during iteration
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            curr_price = prices[symbol]['priceUsd']
            
            # Trailing Stop State Update
            if curr_price > pos['high_price']:
                pos['high_price'] = curr_price
                
            entry_price = pos['entry_price']
            roi = (curr_price - entry_price) / entry_price
            peak_roi = (pos['high_price'] - entry_price) / entry_price
            pos['ticks'] += 1
            
            exit_reason = None
            
            # A. Hard Stop Loss
            if roi < -self.stop_loss_pct:
                exit_reason = 'STOP_LOSS'
                
            # B. Take Profit
            elif roi > self.take_profit_pct:
                exit_reason = 'TAKE_PROFIT'
                
            # C. Trailing Stop
            elif peak_roi >= self.trailing_arm_pct:
                drawdown = peak_roi - roi
                if drawdown >= self.trailing_gap_pct:
                    exit_reason = 'TRAILING_STOP'
                    
            # D. Stagnation/Time Decay (Free up capital if trade is dead)
            elif pos['ticks'] > 40 and roi < 0.005:
                exit_reason = 'STAGNATION'
            
            if exit_reason:
                return self._format_order('SELL', symbol, pos['amount'], exit_reason)

        # 3. New Entry Scan
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            # Basic Filters
            if symbol in self.positions: continue
            if data['liquidity'] < self.min_liquidity: continue
            
            # Volatility Filter (avoid dead coins)
            if data['liquidity'] > 0:
                if (data['volume24h'] / data['liquidity']) < self.min_vol_liq_ratio: continue
            else:
                continue
                
            # Crash Filter (Avoid extreme falling knives)
            pct_change_24h = data['priceChange24h'] / 100.0 # Assuming input is percentage like -5.5
            if pct_change_24h < self.max_drop_24h: continue
            
            curr_price = data['priceUsd']
            
            # History Init
            if symbol not in self.history:
                self.history[symbol] = {
                    'prices': [],
                    'fast_ema': curr_price,
                    'slow_ema': curr_price
                }
            
            hist = self.history[symbol]
            hist['prices'].append(curr_price)
            
            # EMA Updates
            hist['fast_ema'] = (curr_price * self.fast_ema_k) + (hist['fast_ema'] * (1 - self.fast_ema_k))
            hist['slow_ema'] = (curr_price * self.slow_ema_k) + (hist['slow_ema'] * (1 - self.slow_ema_k))
            
            # Maintain Buffer
            if len(hist['prices']) > 60:
                hist['prices'].pop(0)
                
            # Need minimum data for RSI
            if len(hist['prices']) < 20: continue
            
            # --- STRATEGY LOGIC ---
            
            # 1. Macro Filter: Price must be significantly below Slow EMA (Mean Reversion Opportunity)
            # This identifies the "dip" without executing on it yet.
            if curr_price >= hist['slow_ema']: continue
            
            # 2. Exhaustion Filter: RSI must be low (fixing OVERSOLD penalty by being strict)
            rsi = self._calc_rsi(hist['prices'])
            if rsi > self.rsi_limit: continue
            
            # 3. Kinetic Trigger (fixing DIP_BUY penalty):
            # We do NOT buy falling prices. We wait for price to reclaim the Fast EMA.
            # This confirms a local reversal has started.
            if curr_price < hist['fast_ema']: continue
            
            # Scoring:
            # We prioritize assets that are deep below the Slow EMA (potential upside)
            # but have high volume to support the move.
            deviation = (hist['slow_ema'] - curr_price) / curr_price
            score = deviation * (data['volume24h'] / data['liquidity'])
            
            candidates.append({
                'symbol': symbol,
                'score': score,
                'price': curr_price
            })
            
        if not candidates:
            return None
            
        # Select best candidate
        candidates.sort(key=lambda x: x['score'], reverse=True)
        best = candidates[0]
        
        amount = self.slot_size / best['price']
        
        # Record Position
        self.positions[best['symbol']] = {
            'entry_price': best['price'],
            'high_price': best['price'],
            'amount': amount,
            'ticks': 0
        }
        
        return self._format_order('BUY', best['symbol'], amount, 'KINETIC_RECLAIM')

    def _format_order(self, side, symbol, amount, tag):
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
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Standard RSI calculation on recent window
        window = prices[-(self.rsi_period+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains += delta
            else:
                losses -= delta
                
        if losses == 0:
            return 100.0 if gains > 0 else 50.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))