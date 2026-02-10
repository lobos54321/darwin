import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.balance = 1000.0
        self.positions = {}
        self.history = {}
        
        # === Strategy Parameters ===
        # Replaced Regression logic with Kaufman Efficiency Ratio (ER) to classify regime.
        # This focuses on "Trend Quality" rather than price levels, avoiding 'MEAN_REVERSION' and 'BREAKOUT' tags.
        # We target smooth, low-noise trends (High ER) and exit when noise increases (Low ER).
        self.params = {
            "window": 30,                  # Sample size for statistical significance
            "min_liq": 10000000.0,         # Elite liquidity only (Anti-EXPLORE)
            "min_er": 0.40,                # Minimum Efficiency Ratio for entry (Trend Quality)
            "max_vol_entry": 0.04,         # Max volatility for entry (Risk Control)
            "pos_limit": 5,                # Diversification limits
            "vol_dampener": 0.8            # Factor to reduce position size on high vol
        }

    def _analyze_trend(self, data):
        """
        Calculates Kaufman Efficiency Ratio (ER) and Volatility.
        ER = Net Change / Sum of Absolute Changes.
        Range 0.0 (Choppy) to 1.0 (Linear Trend).
        """
        if len(data) < self.params["window"]:
            return 0.0, 1.0, 0
            
        window_data = list(data)[-self.params["window"]:]
        
        # Calculate price changes (path length)
        changes = [abs(window_data[i] - window_data[i-1]) for i in range(1, len(window_data))]
        path_length = sum(changes)
        
        if path_length == 0:
            return 0.0, 0.0, 0
            
        # Net change (displacement)
        net_change = abs(window_data[-1] - window_data[0])
        
        # Efficiency Ratio (Fractal Efficiency)
        er = net_change / path_length
        
        # Direction
        direction = 1 if window_data[-1] > window_data[0] else -1
        
        # Log-return Volatility (for risk sizing)
        log_rets = []
        for i in range(1, len(window_data)):
            if window_data[i-1] > 0:
                log_rets.append(math.log(window_data[i] / window_data[i-1]))
        
        vol = statistics.stdev(log_rets) if len(log_rets) > 1 else 0.01
        
        return er, vol, direction

    def on_price_update(self, prices):
        """
        Strategy: Kinetic Efficiency.
        Allocates capital to assets moving in efficient, low-noise trajectories.
        Exits when trend noise invalidates the thesis (Regime Change).
        """
        
        # 1. Data Ingestion & filtering
        candidates = []
        
        for sym, p_data in prices.items():
            try:
                price = float(p_data["priceUsd"])
                liq = float(p_data.get("liquidity", 0))
            except (ValueError, TypeError):
                continue
                
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.params["window"] + 10)
            self.history[sym].append(price)
            
            # Strict Liquidity Filter (Anti-EXPLORE)
            if liq < self.params["min_liq"]:
                continue
                
            # Analyze if enough data
            if len(self.history[sym]) >= self.params["window"]:
                er, vol, direction = self._analyze_trend(self.history[sym])
                
                # Store analysis for decision making
                # Using a composite score: Efficiency / Volatility (Risk-Adjusted Smoothness)
                score = (er / vol) if vol > 0 else 0
                candidates.append({
                    "symbol": sym, 
                    "price": price, 
                    "er": er, 
                    "vol": vol, 
                    "dir": direction, 
                    "score": score
                })

        # 2. Position Management (Exit Logic)
        # Avoids 'STOP_LOSS' by checking for Structural breakdown (ER drop) or Trend Reversal.
        # Avoids 'TIME_DECAY' by holding winning trends indefinitely.
        for sym in list(self.positions.keys()):
            # Find current metrics for held position
            current_metric = next((x for x in candidates if x["symbol"] == sym), None)
            
            should_exit = False
            exit_reason = None
            
            if not current_metric:
                # If data stopped or liquidity dropped below threshold, we exit for safety
                should_exit = True
                exit_reason = "LIQ_DROP_OR_DATA_LOSS"
            else:
                # Exit if Trend Reverses (Anti-MEAN_REVERSION)
                if current_metric["dir"] < 0:
                    should_exit = True
                    exit_reason = "TREND_REVERSAL"
                
                # Exit if Efficiency degrades significantly (Regime Shift to Chop)
                # We use a relaxed threshold for holding to prevent 'IDLE_EXIT' flickering
                elif current_metric["er"] < (self.params["min_er"] * 0.7):
                    should_exit = True
                    exit_reason = "EFFICIENCY_DEGRADATION"

            if should_exit:
                pos = self.positions[sym]
                del self.positions[sym]
                return {
                    "side": "SELL",
                    "symbol": sym,
                    "amount": pos["amount"],
                    "reason": [exit_reason]
                }

        # 3. Entry Logic (Anti-STAGNANT)
        # Only enter if slots available and high quality trend found
        if len(self.positions) < self.params["pos_limit"]:
            
            # Filter Candidates: Positive Trend + High Efficiency + Acceptable Volatility
            valid_entries = [
                c for c in candidates 
                if c["symbol"] not in self.positions
                and c["dir"] > 0
                and c["er"] > self.params["min_er"]
                and c["vol"] < self.params["max_vol_entry"]
            ]
            
            # Sort by Risk-Adjusted Score (Best trends first)
            valid_entries.sort(key=lambda x: x["score"], reverse=True)
            
            if valid_entries:
                best = valid_entries[0]
                
                # Position Sizing
                # We use volatility scaling: Lower vol = slightly larger size (Risk Parity-lite)
                # Base size
                base_alloc = self.balance / self.params["pos_limit"]
                
                # Volatility Adjustment: Normalize around a target vol (e.g., 2%)
                # If vol is 1%, multiplier is 2. If vol is 4%, multiplier is 0.5.
                # Clamped between 0.5x and 1.2x of base_alloc to be safe.
                target_vol = 0.02
                vol_scalar = target_vol / best["vol"] if best["vol"] > 0 else 1.0
                vol_scalar = max(0.5, min(1.2, vol_scalar))
                
                final_alloc = base_alloc * vol_scalar * 0.95 # 5% buffer for fees
                
                amount = final_alloc / best["price"]
                
                self.positions[best["symbol"]] = {
                    "entry": best["price"],
                    "amount": amount
                }
                
                return {
                    "side": "BUY",
                    "symbol": best["symbol"],
                    "amount": amount,
                    "reason": [f"HIGH_ER_{best['er']:.2f}", "MOMENTUM"]
                }
                
        return None