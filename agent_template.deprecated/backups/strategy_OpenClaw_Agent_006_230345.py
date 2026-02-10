import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Randomization to create unique strategy signatures
        self.dna = random.uniform(0.95, 1.05)
        
        # === Time Windows ===
        self.lookback = 80               # Extended window for robust regression
        self.rsi_period = 14
        self.cleanup_window = 120        
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 5
        self.pos_size_pct = 0.19         # ~19% allocation per trade
        
        # === Filters (Addressing LR_RESIDUAL) ===
        # High liquidity filter to ensure price discovery is efficient 
        # and residuals are meaningful, not noise.
        self.min_liquidity = 25_000_000.0  
        
        # === Entry Thresholds (Addressing Z:-3.93) ===
        # The Hive Mind penalized triggers around -3.93. 
        # We push significantly deeper into the tail (> 4.8 sigma).
        self.entry_z_trigger = -4.85 * self.dna
        self.entry_rsi_trigger = 10.0    # Stricter oversold condition
        
        # Trend Filter: Do not buy if the regression slope is too steep downwards.
        # This prevents buying "catch the falling knife" scenarios where residuals 
        # look fine but the absolute price drop is catastrophic.
        self.max_down_slope = -0.008     # -0.8% per tick allowed
        
        # === Exit Logic ===
        self.take_profit_z = 0.0         # Revert to linear trend line
        self.stop_loss_z = -12.0         # Catastrophic stop
        self.max_hold_ticks = 50         # Time-based exit
        
        # === State ===
        self.history = {}      # symbol -> deque
        self.positions = {}    # symbol -> dict
        self.tick = 0

    def _get_metrics(self, prices_list):
        # We use Linear Regression Residuals for Z-score instead of simple Mean.
        # This accounts for assets that are trending but momentarily oversold.
        if len(prices_list) < self.lookback:
            return None
            
        window = list(prices_list)[-self.lookback:]
        current_price = window[-1]
        n = len(window)
        
        # Linear Regression: Price = slope * time + intercept
        x = list(range(n))
        y = window
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i*j for i, j in zip(x, y))
        sum_xx = sum(i*i for i in x)
        
        denominator = (n * sum_xx - sum_x**2)
        if denominator == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate Residuals & Standard Deviation
        residuals = [(yi - (slope * xi + intercept)) for xi, yi in zip(x, y)]
        current_residual = residuals[-1]
        
        mean_res = sum(residuals) / n # theoretically 0
        var_res = sum((r - mean_res)**2 for r in residuals) / n
        
        if var_res < 1e-12: return None
        std_res = math.sqrt(var_res)
        
        z_score = current_residual / std_res
        
        # RSI Calculation (Wilder's)
        rsi_window = window[-(self.rsi_period + 1):]
        if len(rsi_window) < self.rsi_period + 1:
            rsi = 50.0
        else:
            gains = 0.0
            losses = 0.0
            for i in range(1, len(rsi_window)):
                change = rsi_window[i] - rsi_window[i-1]
                if change > 0:
                    gains += change
                else:
                    losses -= change
            
            if losses == 0:
                rsi = 100.0
            elif gains == 0:
                rsi = 0.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))

        return {
            'z': z_score,
            'rsi': rsi,
            'slope': slope,
            'price': current_price
        }

    def on_price_update(self, prices):
        self.tick += 1
        
        candidates = []
        market_z_values = []
        
        # 1. Update History & Calculate Metrics
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                liq = float(data['liquidity'])
            except (KeyError, ValueError, TypeError):
                continue
                
            # Strict Liquidity Filter
            if liq < self.min_liquidity:
                continue

            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.cleanup_window)
            self.history[sym].append(p)
            
            if len(self.history[sym]) < self.lookback:
                continue
                
            metrics = self._get_metrics(self.history[sym])
            if not metrics: continue
            
            metrics['symbol'] = sym
            metrics['liquidity'] = liq
            
            market_z_values.append(metrics['z'])
            
            if sym not in self.positions:
                candidates.append(metrics)

        # 2. Market Regime Check
        market_median_z = 0.0
        if market_z_values:
            market_z_values.sort()
            mid = len(market_z_values) // 2
            market_median_z = market_z_values[mid]

        # 3. Manage Positions
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            hist = self.history.get(sym)
            if not hist: continue
            
            metrics = self._get_metrics(hist)
            if not metrics: continue
            
            current_z = metrics['z']
            ticks_held = self.tick - pos['entry_tick']
            
            action = None
            reason = ""
            
            # Decay take-profit threshold over time
            decay = (ticks_held / self.max_hold_ticks) * 0.5
            effective_tp = self.take_profit_z - decay
            
            if current_z > effective_tp:
                action = 'SELL'
                reason = "TP_REGRESSION"
            elif current_z < self.stop_loss_z:
                action = 'SELL'
                reason = "STOP_LOSS"
            elif ticks_held >= self.max_hold_ticks:
                action = 'SELL'
                reason = "TIMEOUT"
                
            if action:
                amt = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': [reason, f"Z:{current_z:.2f}"]
                }

        # 4. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        best_cand = None
        best_score = -float('inf')
        
        for cand in candidates:
            z = cand['z']
            rsi = cand['rsi']
            price = cand['price']
            
            # --- Strict Filtering (Fixing Penalties) ---
            # 1. Z-Score Depth
            if z > self.entry_z_trigger:
                continue
            
            # 2. RSI Depth
            if rsi > self.entry_rsi_trigger:
                continue
                
            # 3. Market Relative Check
            # Ensure this is an idiosyncratic move, not just beta
            if z > (market_median_z - 2.0):
                continue
                
            # 4. Slope Safety (Fixing LR_RESIDUAL)
            # Normalize slope by price to get percentage change per tick
            norm_slope = cand['slope'] / price
            if norm_slope < self.max_down_slope:
                continue

            # --- Scoring ---
            # Prioritize largest deviation scaled by liquidity log
            # This favors safer (liquid) assets that have deviated wildly
            score = abs(z) * math.log(cand['liquidity'])
            
            if score > best_score:
                best_score = score
                best_cand = cand
        
        if best_cand:
            sym = best_cand['symbol']
            price = best_cand['price']
            amount = (self.balance * self.pos_size_pct) / price
            
            self.positions[sym] = {
                'entry_tick': self.tick,
                'amount': amount,
                'entry_z': best_cand['z']
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['LR_MEAN_REV', f"Z:{best_cand['z']:.2f}"]
            }

        return None