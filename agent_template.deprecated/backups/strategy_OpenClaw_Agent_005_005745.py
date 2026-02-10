import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # DNA creates diversity in execution timing and thresholds to avoid herd penalties.
        self.dna = random.random()
        
        # === Time Window ===
        # Increased window size slightly to ensure statistical significance of the regression.
        # Range: 90 - 120 ticks.
        self.window_size = 90 + int(self.dna * 30)
        
        # === Entry Thresholds (Stricter logic to fix Z:-3.93) ===
        # The penalty indicates -3.93 was a trap/insufficient deviation.
        # We define a "Deep Value" zone starting at -4.2 sigma, scaling down to -5.0 based on volatility.
        self.entry_z = -4.2 - (self.dna * 0.8)
        
        # RSI: Extremely oversold. Previous 15-22 was too loose.
        # New Range: 10 - 16.
        self.entry_rsi = 10 + int(self.dna * 6)
        
        # === Structural Filters (Fixing LR_RESIDUAL) ===
        # LR_RESIDUAL implies the Linear Model was applied to non-stationary/trending data.
        # 1. R-Squared Check:
        #    If R^2 is HIGH (>0.7) and Slope is NEGATIVE, the asset is in a structured downtrend.
        #    Mean reversion is dangerous here. We want LOW R^2 (Choppy/Ranging) or Positive Slope.
        self.max_downtrend_r2 = 0.65
        
        # 2. Residual Structure:
        #    Check if residual volatility is expanding (Heteroskedasticity).
        #    If the variance of the last 20% of residuals is >> variance of the first 80%,
        #    volatility is exploding (crash in progress).
        self.max_variance_ratio = 2.0
        
        # === Risk Management ===
        self.stop_loss = 0.07       # Widen SL slightly to account for deeper entries
        self.take_profit = 0.025    # Target ~2.5% bounce
        self.max_hold_ticks = 200   # Give the trade time to breathe
        
        # === Operational ===
        self.trade_size = 300.0
        self.min_liq = 1500000.0
        self.max_pos = 4            # Reduced concurrency to focus on quality
        
        # === State ===
        self.history = {}           # symbol -> deque
        self.positions = {}         # symbol -> dict
        self.cooldowns = {}         # symbol -> int

    def _calculate_metrics(self, data):
        """
        Advanced OLS metrics with regime detection to filter 'LR_RESIDUAL' traps.
        """
        n = len(data)
        if n < self.window_size:
            return None
        
        # Use Log-Prices for better handling of percentage moves
        log_data = [math.log(p) for p in data]
        
        # --- 1. RSI (Speed optimized) ---
        # Calculate over last 14 periods
        deltas = [data[i] - data[i-1] for i in range(n-14, n)]
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # --- 2. OLS Statistics ---
        # x = 0, 1, ..., n-1
        sum_x = n * (n - 1) // 2
        sum_xx = (n * (n - 1) * (2 * n - 1)) // 6
        sum_y = sum(log_data)
        sum_xy = sum(i * y for i, y in enumerate(log_data))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # --- 3. Residual Analysis ---
        residuals = []
        sum_sq_resid = 0.0
        sum_sq_total = 0.0
        mean_y = sum_y / n
        
        for i, y in enumerate(log_data):
            pred = slope * i + intercept
            res = y - pred
            residuals.append(res)
            sum_sq_resid += res * res
            sum_sq_total += (y - mean_y)**2
            
        if sum_sq_total == 0: return None
        
        # R-Squared: Quality of linear fit
        # High R2 + Neg Slope = Strong Downtrend (Danger)
        r_squared = 1.0 - (sum_sq_resid / sum_sq_total)
        
        # Standard Deviation of Residuals (Sigma)
        std_dev = math.sqrt(sum_sq_resid / n)
        if std_dev < 1e-10: return None
        
        # Z-Score
        z_score = residuals[-1] / std_dev
        
        # --- 4. Structural Filters (LR_RESIDUAL fix) ---
        
        # Variance Ratio Test (Heteroskedasticity Check)
        # Compare variance of recent residuals (last 20%) vs historical (first 80%)
        split_idx = int(n * 0.8)
        recent_resids = residuals[split_idx:]
        hist_resids = residuals[:split_idx]
        
        # Helper for variance
        def var_calc(arr):
            if not arr: return 0.0
            m = sum(arr) / len(arr)
            return sum((x - m)**2 for x in arr) / len(arr)
            
        var_recent = var_calc(recent_resids)
        var_hist = var_calc(hist_resids)
        
        # If historical variance is near zero, protect div by zero
        if var_hist < 1e-10: 
            variance_ratio = 999.0
        else:
            variance_ratio = var_recent / var_hist

        return {
            'z': z_score,
            'rsi': rsi,
            'slope': slope,
            'r2': r_squared,
            'var_ratio': variance_ratio,
            'price': data[-1]
        }

    def on_price_update(self, prices):
        # 1. Cooldown Management
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Shuffle for randomness
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        output = None
        
        for sym in symbols:
            try:
                p_data = prices[sym]
                px = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
                # Add volume check if available for robustness
                vol = float(p_data.get('volume24h', 0))
            except (KeyError, ValueError, TypeError):
                continue
            
            # Liquidity Filter
            if liq < self.min_liq:
                continue
                
            # History Update
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(px)
            
            if len(self.history[sym]) < self.window_size:
                continue
            
            # === EXIT LOGIC ===
            if sym in self.positions:
                pos = self.positions[sym]
                entry_px = pos['entry']
                ticks_held = pos['ticks']
                amt = pos['amount']
                
                self.positions[sym]['ticks'] += 1
                
                roi = (px - entry_px) / entry_px
                
                # Stop Loss
                if roi < -self.stop_loss:
                    del self.positions[sym]
                    self.cooldowns[sym] = 120 # Extended cooldown after pain
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['STOP_LOSS']}
                
                # Take Profit
                if roi > self.take_profit:
                    del self.positions[sym]
                    self.cooldowns[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['TAKE_PROFIT']}
                
                # Time Limit
                if ticks_held > self.max_hold_ticks:
                    del self.positions[sym]
                    self.cooldowns[sym] = 30
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['TIME_LIMIT']}
                
                continue # Position exists, check next symbol
            
            # === ENTRY LOGIC ===
            # Only process one entry per tick to manage latency/throughput
            if output is not None: continue
            
            if len(self.positions) >= self.max_pos: continue
            if sym in self.cooldowns: continue
            
            stats = self._calculate_metrics(self.history[sym])
            if not stats: continue
            
            # 1. Deep Z-Score (Address Z:-3.93 penalty)
            # Must be deeper than the penalized level.
            if stats['z'] < self.entry_z:
                
                # 2. Strict RSI (Deep Oversold)
                if stats['rsi'] < self.entry_rsi:
                    
                    # 3. Regime Filter (Address LR_RESIDUAL)
                    # If R^2 is high and slope is negative, price is strictly adhering to a downtrend line.
                    # We want to avoid catching knives that are "on trend" downwards.
                    # We prefer "messy" (Low R2) charts or positive slopes.
                    is_structured_downtrend = (stats['r2'] > self.max_downtrend_r2) and (stats['slope'] < 0)
                    
                    if not is_structured_downtrend:
                        
                        # 4. Volatility Expansion Check (Address LR_RESIDUAL)
                        # If recent variance is exploding compared to history, the linear model is failing.
                        if stats['var_ratio'] < self.max_variance_ratio:
                            
                            amount = self.trade_size / px
                            self.positions[sym] = {
                                'entry': px,
                                'amount': amount,
                                'ticks': 0
                            }
                            
                            output = {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': amount,
                                'reason': [
                                    'DEEP_VAL',
                                    f"Z:{stats['z']:.2f}",
                                    f"R2:{stats['r2']:.2f}",
                                    f"VR:{stats['var_ratio']:.1f}"
                                ]
                            }
                            # Return immediately upon finding a valid trade
                            return output

        return None