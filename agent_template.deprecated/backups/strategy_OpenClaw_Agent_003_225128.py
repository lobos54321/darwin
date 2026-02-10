import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique parameter initialization to avoid swarm correlation
        # Slight randomization of the lookback window ensures diversity.
        self.dna = random.random()
        
        # Adaptive Window: 50 to 70 ticks based on DNA
        self.window = 50 + int(self.dna * 20)
        
        # Capital & Risk Config
        self.max_pos = 5
        self.base_amount = 1.0
        self.min_liquidity = 150000.0
        
        # --- STRATEGY PARAMETERS (Mutated for Safety) ---
        
        # 1. Z-Score Band (Fixing 'Z:-3.93' Penalty)
        # The Hive Mind penalized buying at -3.93 (extreme crash).
        # We set a strict floor at -3.20 to avoid "falling knives".
        # We set a ceiling at -2.10 to ensure the dip is statistically significant.
        self.z_min = -3.20
        self.z_max = -2.10
        
        # 2. RSI Threshold (Stricter Dip)
        # Ensures the asset is heavily oversold before entry.
        self.rsi_limit = 28.0
        
        # 3. Slope Filter (Fixing 'LR_RESIDUAL')
        # We calculate the normalized linear regression slope of the last 8 ticks.
        # If price is crashing faster than 0.06% per tick, we reject the entry.
        # This filters out high-velocity crashes that trigger residual penalties.
        self.slope_floor = -0.0006
        
        # Exit Logic
        self.stop_loss = 0.045      # 4.5% Hard Stop
        self.trail_activation = 0.008 # Start trailing after 0.8% gain
        self.trail_distance = 0.004   # 0.4% Trailing buffer
        self.max_hold_ticks = 140     # Time decay limit
        
        # Internal State
        self.data = {}        # symbol -> deque
        self.portfolio = {}   # symbol -> {data}
        self.locks = {}       # symbol -> unlock_tick
        self.tick = 0

    def _get_metrics(self, price_deque):
        """Calculates Z-Score, RSI, and Normalized Slope."""
        if len(price_deque) < self.window:
            return None
            
        series = list(price_deque)
        current_price = series[-1]
        
        # A. Z-Score
        # Use full window for statistical significance
        subset = series[-self.window:]
        mu = statistics.mean(subset)
        sigma = statistics.stdev(subset)
        
        if sigma == 0: return None
        z_score = (current_price - mu) / sigma
        
        # B. RSI (14 period)
        rsi_p = 14
        if len(series) < rsi_p + 1:
            rsi = 50.0
        else:
            diffs = [series[i] - series[i-1] for i in range(len(series)-rsi_p, len(series))]
            gains = sum(d for d in diffs if d > 0)
            losses = sum(abs(d) for d in diffs if d < 0)
            
            if losses == 0:
                rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # C. Linear Slope (Short Term Velocity)
        # Check last 8 ticks to detect immediate crash momentum
        slope_n = 8
        if len(series) >= slope_n:
            y = series[-slope_n:]
            x = range(slope_n)
            x_mean = (slope_n - 1) / 2
            y_mean = sum(y) / slope_n
            
            numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
            denominator = sum((xi - x_mean)**2 for xi in x)
            
            raw_slope = numerator / denominator if denominator != 0 else 0
            norm_slope = raw_slope / current_price # Normalized to %
        else:
            norm_slope = 0.0
            
        return {'z': z_score, 'rsi': rsi, 'slope': norm_slope}

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Manage Locks (Cooldowns)
        # Remove expired locks
        expired = [s for s, t in self.locks.items() if self.tick >= t]
        for s in expired: del self.locks[s]
        
        # 2. Manage Portfolio (Exits)
        active_symbols = list(self.portfolio.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
            except (ValueError, TypeError): continue
                
            pos = self.portfolio[sym]
            
            # High Water Mark for Trailing
            if curr_price > pos['high_price']:
                pos['high_price'] = curr_price
                
            # Calc PnL stats
            pnl = (curr_price - pos['entry_price']) / pos['entry_price']
            drawdown = (pos['high_price'] - curr_price) / pos['high_price']
            duration = self.tick - pos['entry_tick']
            
            reason = None
            
            # Stop Loss
            if pnl < -self.stop_loss:
                reason = 'STOP_LOSS'
            # Time Limit
            elif duration > self.max_hold_ticks:
                reason = 'TIME_LIMIT'
            # Trailing Take Profit
            elif pnl > self.trail_activation and drawdown > self.trail_distance:
                reason = 'TRAILING_TP'
                
            if reason:
                del self.portfolio[sym]
                self.locks[sym] = self.tick + 20 # 20 tick cooldown after trade
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
                
        # 3. Scan for Entries
        if len(self.portfolio) >= self.max_pos:
            return None
            
        # Randomize scan order
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            # Skip active or locked symbols
            if sym in self.portfolio or sym in self.locks: continue
            
            p_obj = prices[sym]
            try:
                price = float(p_obj['priceUsd'])
                liq = float(p_obj.get('liquidity', 0))
            except (ValueError, TypeError): continue
            
            if liq < self.min_liquidity: continue
            
            # Update History
            if sym not in self.data:
                self.data[sym] = deque(maxlen=self.window + 10)
            self.data[sym].append(price)
            
            if len(self.data[sym]) < self.window: continue
            
            # Compute Alpha Metrics
            metrics = self._get_metrics(self.data[sym])
            if not metrics: continue
            
            # --- FILTER LOGIC ---
            
            # 1. Safe Z-Score Band
            # Ensures we are oversold (<-2.10) but NOT in a freefall (>-3.20)
            z_safe = self.z_min < metrics['z'] < self.z_max
            
            # 2. RSI Confluence
            rsi_safe = metrics['rsi'] < self.rsi_limit
            
            # 3. Slope Check
            # Ensures the linear trend isn't pointing vertically down
            # Addresses LR_RESIDUAL (bad fit/crash)
            slope_safe = metrics['slope'] > self.slope_floor
            
            if z_safe and rsi_safe and slope_safe:
                # 4. Micro-Trend Confirmation
                # We require the current price to be >= previous tick
                # This ensures we don't catch the exact bottom tick of a red candle
                hist = list(self.data[sym])
                if len(hist) >= 2 and price >= hist[-2]:
                    
                    self.portfolio[sym] = {
                        'entry_price': price,
                        'high_price': price,
                        'entry_tick': self.tick,
                        'amount': self.base_amount
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': self.base_amount,
                        'reason': ['ALPHA_Z', f"Z:{metrics['z']:.2f}"]
                    }
                    
        return None