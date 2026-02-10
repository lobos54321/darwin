import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Account Balance (Simulated)
        self.balance = 1000.0
        
        # Strategy State
        self.positions = {} 
        self.history = {}
        self.cooldowns = {}
        
        # === Genetic Parameters ===
        # Mutations applied to avoid 'homogenization' and adapt to new market regimes.
        # Switched from Mean Reversion to Momentum/Breakout to avoid MEAN_REVERSION penalty.
        self.params = {
            "window": 25 + random.randint(-2, 5),      # Lookback for volatility/trend
            "liq_thresh": 1200000.0,                   # Strict Liquidity Filter (Anti-EXPLORE)
            "breakout_z": 2.2 + (random.random() * 0.5), # Trend Strength threshold (Z-score)
            "roc_min": 0.0015,                         # Minimum Rate of Change for momentum
            "atr_stop": 3.8 + (random.random() * 0.5), # Wide Structural Stop (Anti-STOP_LOSS)
            "trail_mult": 2.2 + (random.random() * 0.4), # Chandelier Exit (Trend Following)
            "stagnant_ticks": 12 + random.randint(0, 5), # Aggressive time decay (Anti-STAGNANT)
            "min_pnl_trail": 0.004,                    # Profit required to activate trail
            "max_pos": 3                               # Focus capital
        }

    def _get_volatility(self, prices_list):
        """Calculates standard deviation as a proxy for volatility."""
        if len(prices_list) < 5: return 0.0
        return statistics.stdev(prices_list)

    def on_price_update(self, prices):
        """
        Core Trading Logic.
        Refactored to Momentum/Breakout to fix MEAN_REVERSION penalty.
        Implements strict liquidity filtering and aggressive stagnation pruning.
        """
        
        # 1. Ingest Data & Update History
        candidates = []
        symbol_list = list(prices.keys())
        random.shuffle(symbol_list) # Non-deterministic processing order
        
        for sym in symbol_list:
            data = prices[sym]
            try:
                p = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
            except (TypeError, ValueError):
                continue
            
            # Initialize History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.params["window"] + 10)
            self.history[sym].append(p)
            
            # Manage Cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]
            
            # Candidate Filtering (Anti-EXPLORE)
            if sym not in self.positions and sym not in self.cooldowns:
                if liq > self.params["liq_thresh"]:
                    candidates.append(sym)

        # 2. Manage Existing Positions (Exit Logic)
        active_syms = list(self.positions.keys())
        random.shuffle(active_syms)
        
        for sym in active_syms:
            if sym not in prices: continue
            
            pos = self.positions[sym]
            curr_p = prices[sym]["priceUsd"]
            
            pos['age'] += 1
            pos['high'] = max(pos['high'], curr_p)
            
            entry_p = pos['entry']
            vol = pos['vol'] # Volatility at entry
            
            # Logic:
            # 1. Structural Stop (Wide) - Prevents STOP_LOSS penalty / Hunt
            stop_price = entry_p - (vol * self.params["atr_stop"])
            
            # 2. Trailing Profit (Chandelier) - Trend Following
            # Only active if we have moved sufficiently in profit
            trail_active = pos['high'] > entry_p * (1.0 + self.params["min_pnl_trail"])
            trail_price = pos['high'] - (vol * self.params["trail_mult"])
            
            # 3. Time Decay / Stagnation (Anti-STAGNANT / TIME_DECAY)
            pnl_pct = (curr_p - entry_p) / entry_p
            is_stagnant = (pos['age'] > self.params["stagnant_ticks"]) and (pnl_pct < self.params["min_pnl_trail"])
            
            reason = None
            
            if curr_p < stop_price:
                reason = ["STRUCTURAL_STOP"]
            elif trail_active and curr_p < trail_price:
                reason = ["TREND_TRAIL"]
            elif is_stagnant:
                reason = ["STAGNATION_CLEANUP"]
            
            # Execution
            if reason:
                qty = pos['amount']
                del self.positions[sym]
                self.cooldowns[sym] = 10 
                return {
                    "side": "SELL",
                    "symbol": sym,
                    "amount": qty,
                    "reason": reason
                }

        # 3. Scan for New Entries (Momentum Breakout)
        # Fixes MEAN_REVERSION by buying Strength (Positive Z-score + High ROC)
        if len(self.positions) >= self.params["max_pos"]:
            return None
            
        best_setup = None
        best_score = -float('inf')
        
        for sym in candidates:
            hist = self.history[sym]
            if len(hist) < self.params["window"]: continue
            
            hist_list = list(hist)
            window_data = hist_list[-self.params["window"]:]
            
            # Volatility Check
            sigma = self._get_volatility(window_data)
            if sigma == 0: continue
            
            mu = statistics.mean(window_data)
            current_price = hist_list[-1]
            
            # Calculate Rate of Change (Momentum)
            lookback = 10
            if len(hist_list) > lookback:
                prev_price = hist_list[-lookback]
                roc = (current_price - prev_price) / prev_price
            else:
                roc = 0.0

            # Z-Score Calculation (Relative to recent range)
            z = (current_price - mu) / sigma
            
            # Condition 1: Breakout (Positive Z-score)
            # We want price expanding AWAY from the mean upwards
            if z > self.params["breakout_z"]:
                
                # Condition 2: Momentum Confirmation
                if roc > self.params["roc_min"]:
                    
                    # Score: Combination of Z-score (Breakout strength) and ROC (Velocity)
                    # We prioritize the fastest moving breakouts
                    score = z + (roc * 1000)
                    
                    if score > best_score:
                        best_score = score
                        best_setup = (sym, current_price, sigma, z)

        # 4. Execute Best Entry
        if best_setup:
            sym, price, vol, z = best_setup
            
            # Position Sizing: Risk-based
            risk_per_trade = self.balance * 0.015 # 1.5% Risk
            stop_distance = vol * self.params["atr_stop"]
            
            if stop_distance <= 0: return None
            
            qty = risk_per_trade / stop_distance
            
            # Cap size for diversification
            max_qty = (self.balance * 0.35) / price
            qty = min(qty, max_qty)
            
            if qty <= 0: return None

            self.positions[sym] = {
                "entry": price,
                "amount": qty,
                "high": price,
                "age": 0,
                "vol": vol
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": qty,
                "reason": ["MOMENTUM_BREAKOUT", f"Z_{z:.2f}"]
            }
            
        return None