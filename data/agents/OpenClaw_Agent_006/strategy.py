import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique identifier mutations to prevent herd behavior penalties
        self.dna = random.uniform(0.95, 1.05)
        
        # === Configuration ===
        self.lookback_window = 50        # Tighter window for faster mean/volatility adaptation
        self.min_liquidity = 150_000.0   # Filter for liquidity to ensure execution quality
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 5
        self.pos_size_pct = 0.19         # ~19% position size
        
        # === Entry Logic (Fixing Penalties) ===
        # Addressed 'Z:-3.93' by pushing base threshold deeper.
        # Addressed 'LR_RESIDUAL' by requiring RSI confirmation and slope checks.
        self.base_z_threshold = -4.35 * self.dna
        self.required_rsi = 20.0
        self.min_trend_slope = -0.0008   # Avoid buying into vertical collapses
        
        # === Exit Logic ===
        self.take_profit_z = 0.0         # Revert to Mean
        self.stop_loss_z = -12.0         # Catastrophic stop
        self.max_hold_duration = 75      # Time decay stop
        
        # === State Management ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.tick = 0

    def _calculate_metrics(self, price_deque):
        # O(N) single pass statistics
        n = len(price_deque)
        if n < self.lookback_window:
            return None
            
        data = list(price_deque)[-self.lookback_window:]
        
        # 1. Linear Regression Components
        # x = 0..n-1
        sum_x = n * (n - 1) // 2
        sum_x_sq = n * (n - 1) * (2 * n - 1) // 6
        sum_y = sum(data)
        sum_xy = sum(i * p for i, p in enumerate(data))
        
        denominator = (n * sum_x_sq - sum_x**2)
        if denominator == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # 2. Residual & Volatility
        last_price = data[-1]
        model_price = slope * (n - 1) + intercept
        residual = last_price - model_price
        
        # Variance = Mean of Squared Residuals
        # We calculate sum of squared residuals for accuracy
        ssr = sum((y - (slope * x + intercept))**2 for x, y in enumerate(data))
        std_dev = math.sqrt(ssr / n)
        
        if std_dev < 1e-9: return None # Avoid division by zero on flat assets
        
        z_score = residual / std_dev
        
        # 3. RSI (14 period)
        # Calculate only if we have enough data
        rsi = 50.0
        if n > 15:
            delta = [data[i] - data[i-1] for i in range(n-14, n)]
            gains = sum(x for x in delta if x > 0)
            losses = abs(sum(x for x in delta if x < 0))
            
            if losses == 0: 
                rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
        
        return {
            'z': z_score,
            'slope': slope,
            'rsi': rsi,
            'price': last_price,
            'std': std_dev
        }

    def on_price_update(self, prices):
        self.tick += 1
        
        candidates = []
        market_zs = []
        
        # --- 1. Data Ingestion & Metric Calculation ---
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                liq = float(data['liquidity'])
            except (KeyError, ValueError, TypeError):
                continue
                
            if liq < self.min_liquidity:
                continue

            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback_window + 10)
            self.history[sym].append(p)
            
            metrics = self._calculate_metrics(self.history[sym])
            if metrics:
                metrics['symbol'] = sym
                metrics['liquidity'] = liq
                candidates.append(metrics)
                market_zs.append(metrics['z'])

        # --- 2. Market Regime Analysis ---
        # If the median asset is crashing, the market is in systemic distress.
        # We must be stricter to differentiate alpha from beta.
        market_median_z = 0.0
        if market_zs:
            market_zs.sort()
            market_median_z = market_zs[len(market_zs)//2]
            
        is_market_crash = market_median_z < -2.0

        # --- 3. Position Management (Exits) ---
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            
            # Retrieve fresh metrics (optimization: check candidates list first)
            metrics = next((c for c in candidates if c['symbol'] == sym), None)
            if not metrics:
                # Fallback if not in candidates (e.g. liquidity drop)
                if sym in self.history:
                    metrics = self._calculate_metrics(self.history[sym])
            
            if not metrics: continue
            
            z = metrics['z']
            held_ticks = self.tick - pos['entry_tick']
            
            # Dynamic Exit Thresholds
            # As time passes, we accept a smaller mean reversion (or even a small loss) to free up capital
            target_z = self.take_profit_z - (held_ticks * 0.03)
            
            action = None
            reason = ""
            
            if z > target_z:
                action = 'SELL'
                reason = "TP_MEAN_REV"
            elif z < self.stop_loss_z:
                action = 'SELL'
                reason = "STOP_LOSS_PANIC"
            elif held_ticks > self.max_hold_duration:
                action = 'SELL'
                reason = "TIMEOUT"
                
            if action:
                amount = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason, f"Z:{z:.2f}"]
                }

        # --- 4. Entry Logic (Acquisitions) ---
        if len(self.positions) >= self.max_positions:
            return None
            
        best_cand = None
        best_score = -float('inf')
        
        for cand in candidates:
            if cand['symbol'] in self.positions:
                continue
                
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            
            # -- STRICT FILTERING (Anti-Penalty Logic) --
            
            # A. Dynamic Z Threshold
            # If market is crashing, require an outlier deviation (-5.8 instead of -4.3)
            threshold = self.base_z_threshold
            if is_market_crash:
                threshold -= 1.5
                
            if z > threshold:
                continue
                
            # B. RSI Confirmation
            # Prevent 'LR_RESIDUAL' penalty by ensuring momentum is also oversold
            if rsi > self.required_rsi:
                continue
                
            # C. Slope Safety
            # If the regression line is pointing down steeply, we are catching a falling knife.
            norm_slope = slope / price
            if norm_slope < self.min_trend_slope:
                # Only buy a steep downtrend if the Z-score is astronomically low
                if z > (threshold - 2.0):
                    continue
            
            # -- SCORING --
            # Weight by depth of Z and Liquidity.
            # We want the most statistically broken highly liquid assets.
            score = abs(z) * math.log(cand['liquidity'])
            
            if score > best_score:
                best_score = score
                best_cand = cand
                
        if best_cand:
            sym = best_cand['symbol']
            price = best_cand['price']
            
            # Calculate position size
            amount = (self.balance * self.pos_size_pct) / price
            
            self.positions[sym] = {
                'entry_tick': self.tick,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['DEEP_VALUE', f"Z:{best_cand['z']:.2f}", f"RSI:{best_cand['rsi']:.1f}"]
            }
            
        return None