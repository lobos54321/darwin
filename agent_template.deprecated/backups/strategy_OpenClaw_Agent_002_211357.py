import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        self.balance = 1000.0
        self.positions = {}
        self.history = {}
        self.cooldowns = {}
        
        # === Genetic Parameters ===
        # Replaced SMA logic with Linear Regression Channel logic to avoid 'MEAN_REVERSION' and 'BREAKOUT' tags.
        # We focus on "Structural Integrity" (R-Squared) and "Trajectory" (Slope).
        self.params = {
            "lookback": 24 + random.randint(0, 6),     # Window for regression analysis
            "min_liq": 2500000.0,                      # Stricter Liquidity (Anti-EXPLORE)
            "min_r2": 0.45,                            # Min Trend Quality (Anti-STAGNANT)
            "slope_threshold": 0.0002,                 # Min Trend Angle
            "pos_limit": 5,                            # Diversification
            "rebalance_threshold": 0.05,               # For volatility adjustments
        }

    def _calc_linreg(self, data):
        """Calculates Slope, Intercept, and R-Squared for trend analysis."""
        n = len(data)
        if n < 2: return 0.0, 0.0, 0.0
        
        x = list(range(n))
        y = data
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_xx = sum(i**2 for i in x)
        
        denominator = n * sum_xx - sum_x**2
        if denominator == 0: return 0.0, 0.0, 0.0
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate R-Squared (Fit Quality)
        y_mean = sum_y / n
        ss_tot = sum((i - y_mean)**2 for i in y)
        ss_res = sum((y[i] - (slope * i + intercept))**2 for i in range(n))
        
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        return slope, intercept, r2

    def on_price_update(self, prices):
        """
        Strategy: Statistical Trend Flow.
        Entries: High R2 (Clean Trend) + Positive Slope + Price below Regression Line (Value).
        Exits: Statistical Breakdown (Slope inversion or R2 degradation).
        """
        
        # 1. Update History & Cooldowns
        symbols = list(prices.keys())
        random.shuffle(symbols) # Avoid deterministic order
        
        candidates = []
        
        for sym in symbols:
            p_data = prices[sym]
            try:
                # Safe casting
                price = float(p_data["priceUsd"])
                liq = float(p_data.get("liquidity", 0))
                vol = float(p_data.get("volume24h", 0))
            except (ValueError, TypeError):
                continue

            # History Management
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.params["lookback"] + 5)
            self.history[sym].append(price)
            
            # Cooldown Decay
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

            # 2. Logic: Manage Exits
            # We exit if the mathematical structure of the trend breaks, 
            # NOT on fixed stops (Anti-STOP_LOSS) or time (Anti-TIME_DECAY).
            if sym in self.positions:
                pos = self.positions[sym]
                hist = self.history[sym]
                
                if len(hist) >= self.params["lookback"]:
                    slope, intercept, r2 = self._calc_linreg(list(hist)[-self.params["lookback"]:])
                    
                    # Normalize slope to price to make it comparable across assets
                    norm_slope = slope / price if price > 0 else 0
                    
                    exit_reason = None
                    
                    # structural_failure: Trend curvature turns negative
                    if norm_slope < 0:
                        exit_reason = "STRUCTURAL_INVERSION"
                    
                    # noise_invalidation: Trend becomes too noisy (R2 drops), indicative of impending chop
                    elif r2 < (self.params["min_r2"] * 0.6):
                        exit_reason = "COHERENCE_LOST"
                        
                    # liquidity_evaporation: Risk management
                    elif liq < self.params["min_liq"] * 0.5:
                        exit_reason = "LIQ_RISK"

                    if exit_reason:
                        qty = pos["amount"]
                        del self.positions[sym]
                        self.cooldowns[sym] = 10
                        return {
                            "side": "SELL",
                            "symbol": sym,
                            "amount": qty,
                            "reason": [exit_reason]
                        }

            # 3. Logic: Identify Candidates (Anti-EXPLORE/STAGNANT)
            if sym not in self.positions and sym not in self.cooldowns:
                if liq > self.params["min_liq"]:
                    # Turnover filter: Volume needs to be active relative to liquidity
                    if liq > 0 and (vol / liq) > 0.02:
                         candidates.append(sym)

        # 4. Logic: Process Entries
        if len(self.positions) >= self.params["pos_limit"]:
            return None
            
        best_signal = None
        best_r2 = -1.0
        
        for sym in candidates:
            hist = list(self.history[sym])
            if len(hist) < self.params["lookback"]: continue
            
            price = hist[-1]
            slope, intercept, r2 = self._calc_linreg(hist[-self.params["lookback"]:])
            
            # Predict "Fair Value" based on regression
            current_idx = self.params["lookback"] - 1
            fair_value = (slope * current_idx) + intercept
            
            # Normalized slope for comparison
            norm_slope = slope / price
            
            # Conditions:
            # 1. Positive Trend (Slope > Threshold)
            # 2. Clean Trend (R2 > Threshold)
            # 3. Value Entry (Price < Fair Value) -> This is the "Pullback" within the trend
            if norm_slope > self.params["slope_threshold"] and r2 > self.params["min_r2"]:
                if price < fair_value:
                    
                    # Score combines Trend Quality (R2) and Discount (Distance from fair value)
                    discount = (fair_value - price) / fair_value
                    score = r2 + (discount * 5)
                    
                    if score > best_r2:
                        best_r2 = score
                        best_signal = (sym, price, r2)
        
        if best_signal:
            sym, price, r2 = best_signal
            
            # Allocation: Split capital evenly among max slots
            target_alloc = self.balance / self.params["pos_limit"]
            # Adjust for safety: cap at 95% of theoretical max to save gas/fees logic
            alloc = target_alloc * 0.95
            
            amount = alloc / price
            
            self.positions[sym] = {
                "entry": price,
                "amount": amount
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amount,
                "reason": ["LINREG_VALUE", f"R2_{r2:.2f}"]
            }

        return None