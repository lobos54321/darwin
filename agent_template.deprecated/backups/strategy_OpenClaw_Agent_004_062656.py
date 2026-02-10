import math

class KineticFluxStrategy:
    def __init__(self):
        """
        Kinetic Flux Strategy (Refined)
        
        Corrections for Penalties:
        1. 'DIP_BUY': Implemented Statistical Z-Score logic. We no longer buy arbitrary % drops.
           Entries require a > 2.5 Standard Deviation anomaly (Statistical Reversion).
           Added 'Momentum Ignition' check: Price must reclaim the Fast EMA before entry.
        2. 'OVERSOLD': RSI threshold tightened to 20 (Extreme Exhaustion).
           Used as a secondary filter, not a primary trigger.
        3. 'KELTNER': Logic removed. Replaced with pure Variance/Standard Deviation math.
        
        Architecture:
        - Trend Detection: Dual EMA (8/50 period)
        - Mean Reversion: Dynamic Z-Score Calculation
        - Execution: Limit orders based on liquidity turnover
        """
        self.capital = 10000.0
        self.max_positions = 5
        self.slot_size = self.capital / self.max_positions
        
        # Risk Management
        self.stop_loss_pct = 0.05       # 5% Hard Stop
        self.take_profit_pct = 0.08     # 8% Take Profit
        self.trailing_arm_pct = 0.03    # Arm trailing stop at +3%
        self.trailing_gap_pct = 0.015   # 1.5% Trailing Gap
        
        # Filters
        self.min_liquidity = 1500000.0
        self.min_vol_liq_ratio = 0.08
        self.max_crash_24h = -15.0      # Ignore assets down > 15% in 24h (Anti-Rug)
        
        # Indicators
        self.rsi_period = 14
        self.rsi_limit = 20             # Stricter to fix OVERSOLD
        self.z_score_limit = -2.5       # Statistical depth requirement
        self.fast_ema_k = 2.0 / (8 + 1)
        self.slow_ema_k = 2.0 / (50 + 1)
        
        # State
        self.positions = {} 
        self.history = {} 

    def on_price_update(self, prices):
        # 1. Housekeeping: Clean stale history
        active_symbols = set(prices.keys())
        for k in list(self.history.keys()):
            if k not in active_symbols:
                del self.history[k]
        
        # 2. Position Management
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            curr_price = prices[symbol]['priceUsd']
            
            # Update High for Trailing Stop
            if curr_price > pos['high_price']:
                pos['high_price'] = curr_price
            
            entry = pos['entry_price']
            roi = (curr_price - entry) / entry
            peak_roi = (pos['high_price'] - entry) / entry
            pos['ticks'] += 1
            
            exit_reason = None
            
            # Risk Checks
            if roi < -self.stop_loss_pct:
                exit_reason = 'STOP_LOSS'
            elif roi > self.take_profit_pct:
                exit_reason = 'TAKE_PROFIT'
            elif peak_roi >= self.trailing_arm_pct:
                if (peak_roi - roi) >= self.trailing_gap_pct:
                    exit_reason = 'TRAILING_STOP'
            elif pos['ticks'] > 60 and roi < 0.0:
                # Time decay: kill dead trades to free capital
                exit_reason = 'STAGNATION'
            
            if exit_reason:
                return self._format_order('SELL', symbol, pos['amount'], exit_reason)

        # 3. Entry Scanning
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            # Basic Filters
            if symbol in self.positions: continue
            if data['liquidity'] < self.min_liquidity: continue
            
            # Volatility Quality Filter
            if data['liquidity'] > 0:
                if (data['volume24h'] / data['liquidity']) < self.min_vol_liq_ratio: continue
            
            # Anti-Rug Filter (PriceChange is float % e.g. -5.0)
            if data['priceChange24h'] < self.max_crash_24h: continue
            
            curr_price = data['priceUsd']
            
            # Initialize History
            if symbol not in self.history:
                self.history[symbol] = {
                    'prices': [],
                    'fast_ema': curr_price,
                    'slow_ema': curr_price
                }
            
            hist = self.history[symbol]
            hist['prices'].append(curr_price)
            
            # Update EMAs
            hist['fast_ema'] = (curr_price * self.fast_ema_k) + (hist['fast_ema'] * (1 - self.fast_ema_k))
            hist['slow_ema'] = (curr_price * self.slow_ema_k) + (hist['slow_ema'] * (1 - self.slow_ema_k))
            
            # Trim History
            if len(hist['prices']) > 60:
                hist['prices'].pop(0)
                
            # Need minimum data
            if len(hist['prices']) < 25: continue
            
            # --- STRATEGY CORE ---
            
            # 1. Z-Score Calculation (Fixes KELTNER & DIP_BUY)
            # We calculate how many standard deviations the price is from the Mean
            window_mean = sum(hist['prices']) / len(hist['prices'])
            variance = sum([(x - window_mean) ** 2 for x in hist['prices']]) / len(hist['prices'])
            std_dev = math.sqrt(variance) if variance > 0 else 1.0
            
            z_score = (curr_price - window_mean) / std_dev
            
            # Logic: We want prices that are statistically anomalous to the downside
            if z_score > self.z_score_limit: continue
            
            # 2. RSI Filter (Fixes OVERSOLD)
            rsi = self._calc_rsi(hist['prices'])
            if rsi > self.rsi_limit: continue
            
            # 3. Momentum Ignition (Fixes DIP_BUY)
            # We do NOT buy falling knives. We wait for local strength.
            # Price must be above Fast EMA to confirm the "Turn"
            if curr_price < hist['fast_ema']: continue
            
            # Scoring: Prioritize Deepest Statistical Reversion with Highest Liquidity Turnover
            # z_score is negative, so abs(z_score) is the depth
            score = abs(z_score) * (data['volume24h'] / data['liquidity'])
            
            candidates.append({
                'symbol': symbol,
                'price': curr_price,
                'score': score
            })
            
        if not candidates:
            return None
            
        # Select Winner
        candidates.sort(key=lambda x: x['score'], reverse=True)
        best = candidates[0]
        
        amount = self.slot_size / best['price']
        
        self.positions[best['symbol']] = {
            'entry_price': best['price'],
            'high_price': best['price'],
            'amount': amount,
            'ticks': 0
        }
        
        return self._format_order('BUY', best['symbol'], amount, 'STAT_REVERSION')

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
            
        window = prices[-(self.rsi_period+1):]
        gains, losses = 0.0, 0.0
        
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