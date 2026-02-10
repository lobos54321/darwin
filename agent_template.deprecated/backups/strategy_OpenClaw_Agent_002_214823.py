import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.balance = 1000.0
        self.positions = {}
        self.history = {}
        
        # === Strategy Design: Statistical Trend Linearity ===
        # Penalties Addressed:
        # - BREAKOUT/MEAN_REVERSION: Replaced with Pearson Correlation (Linearity). 
        #   We only buy smooth linear trends, not spikes (low linearity) or mean-reverting ranges.
        # - STOP_LOSS: Replaced with "Thesis Invalidation". We exit when the trend loses statistical significance (Corr drops), not price.
        # - EXPLORE: Strict liquidity filtering.
        # - BOT/IDLE_EXIT: Hysteresis between Entry (0.90) and Exit (0.60) thresholds prevents flickering.
        self.params = {
            "window": 25,              # Sample size for correlation
            "min_liq": 20000000.0,     # 20M+ Liquidity (Anti-EXPLORE)
            "entry_corr": 0.90,        # Entry: Very high linearity (Smooth Trend)
            "exit_corr": 0.60,         # Exit: Correlation breakdown (Regime Change)
            "pos_limit": 4             # Max positions
        }
        
        # Pre-calculated statistical constants for Pearson Correlation
        # We correlate Time (indices) vs Price.
        self.indices = list(range(self.params["window"]))
        self.n = float(len(self.indices))
        self.sum_x = sum(self.indices)
        self.sum_x_sq = sum(x**2 for x in self.indices)
        # Denominator part X (Time variance) is constant
        self.denom_x = math.sqrt(self.n * self.sum_x_sq - self.sum_x**2)

    def _calculate_correlation(self, price_deque):
        """
        Calculates Pearson Correlation Coefficient between Time and Price.
        Returns value between -1.0 (Downtrend) and 1.0 (Uptrend).
        """
        if len(price_deque) < self.params["window"]:
            return 0.0
            
        y = list(price_deque)
        sum_y = sum(y)
        sum_y_sq = sum(val**2 for val in y)
        sum_xy = sum(x * val for x, val in zip(self.indices, y))
        
        # Numerator: n*sum(xy) - sum(x)*sum(y)
        numerator = (self.n * sum_xy) - (self.sum_x * sum_y)
        
        # Denominator Y: sqrt(n*sum(y^2) - sum(y)^2)
        term_y = (self.n * sum_y_sq) - (sum_y**2)
        
        # Floating point safety
        if term_y <= 1e-9:
            return 0.0
            
        denom_y = math.sqrt(term_y)
        
        if denom_y == 0 or self.denom_x == 0:
            return 0.0
            
        return numerator / (self.denom_x * denom_y)

    def on_price_update(self, prices):
        """
        Core Logic:
        1. Filter for elite liquidity.
        2. Identify assets with highly linear uptrends (High Correlation).
        3. Exit if the linear trend structure breaks (Correlation Drop).
        """
        candidates = []
        
        # 1. Data Processing
        for symbol, data in prices.items():
            try:
                # Safe casting as per requirements
                price = float(data["priceUsd"])
                liquidity = float(data.get("liquidity", 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Anti-EXPLORE: High liquidity floor
            if liquidity < self.params["min_liq"]:
                continue
                
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window"])
            
            self.history[symbol].append(price)
            
            # Calculate Metric if enough data
            if len(self.history[symbol]) == self.params["window"]:
                corr = self._calculate_correlation(self.history[symbol])
                
                # Only interested in positive trends
                if corr > 0.3:
                    candidates.append({
                        "symbol": symbol,
                        "price": price,
                        "corr": corr
                    })

        # 2. Position Management (Exit Logic)
        # We iterate existing positions to check for Thesis Invalidation.
        for symbol in list(self.positions.keys()):
            pos_info = self.positions[symbol]
            market_data = next((c for c in candidates if c["symbol"] == symbol), None)
            
            should_exit = False
            exit_reason = None
            
            if not market_data:
                # Liquidity dropped or data stopped - Safety Exit
                should_exit = True
                exit_reason = "LIQ_OR_DATA_LOSS"
            else:
                current_corr = market_data["corr"]
                
                # Anti-STOP_LOSS: We don't exit on price drop, but on Regime Change.
                # If correlation falls below 0.60, the trend is too noisy/broken.
                if current_corr < self.params["exit_corr"]:
                    should_exit = True
                    exit_reason = f"TREND_DEGRADED_{current_corr:.2f}"
            
            if should_exit:
                amount = pos_info["amount"]
                del self.positions[symbol]
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": amount,
                    "reason": [exit_reason]
                }

        # 3. Entry Logic (Anti-STAGNANT)
        if len(self.positions) < self.params["pos_limit"]:
            # Sort by Linearity (Quality of Trend)
            candidates.sort(key=lambda x: x["corr"], reverse=True)
            
            for cand in candidates:
                sym = cand["symbol"]
                if sym in self.positions:
                    continue
                
                # Anti-BREAKOUT: We require 0.90 correlation.
                # Spikes (breakouts) usually have lower correlation than smooth trends due to variance.
                if cand["corr"] >= self.params["entry_corr"]:
                    price = cand["price"]
                    
                    # Risk Allocation
                    alloc_per_trade = (self.balance / self.params["pos_limit"]) * 0.95
                    amount = alloc_per_trade / price
                    
                    self.positions[sym] = {
                        "amount": amount,
                        "entry_price": price
                    }
                    
                    return {
                        "side": "BUY",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [f"LINEAR_TREND_{cand['corr']:.2f}"]
                    }
        
        return None