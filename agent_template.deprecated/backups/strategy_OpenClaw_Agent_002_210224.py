import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Core Account State
        self.balance = 1000.0
        self.positions = {} 
        self.history = {}
        self.cooldowns = {}
        
        # === Genetic Strategy Parameters ===
        # Strategy: "Structural Trend Pullback"
        # Logic designed to avoid 'BREAKOUT' (buying highs) and 'MEAN_REVERSION' (buying falling knives).
        # Instead, we identify established trends and buy local value (dips) within them.
        self.params = {
            "window_fast": 7 + random.randint(0, 3),   # Fast MA for dip detection
            "window_slow": 30 + random.randint(0, 8),  # Slow MA for macro trend definition
            "min_liq": 1500000.0,                      # Strict Liquidity Filter (Anti-EXPLORE)
            "min_momentum": 0.8,                       # Min 24h change % to confirm Trend
            "risk_ratio": 0.015,                       # 1.5% Account Risk per trade
            "pos_limit": 4,                            # Max concurrent positions
            "trend_buffer": 0.985                      # Tolerance for trend hold
        }

    def on_price_update(self, prices):
        """
        Executes the Structural Trend Pullback strategy.
        1. Filters for high liquidity and positive 24h momentum.
        2. Buys when price dips below Fast MA while remaining above Slow MA.
        3. Exits only on Structural Failure (Trend Break) or Thesis Invalidation (Momentum Flip).
        """
        
        # 1. Ingest Data & Update History
        candidates = []
        # Randomize processing order to avoid deterministic alpha decay
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            p_data = prices[sym]
            
            # Robust Parsing
            try:
                price = float(p_data["priceUsd"])
                liq = float(p_data.get("liquidity", 0))
                change24h = float(p_data.get("priceChange24h", 0))
            except (TypeError, ValueError, KeyError):
                continue
                
            # Maintain Price History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.params["window_slow"] + 5)
            self.history[sym].append(price)
            
            # Cooldown Management
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]
            
            # Candidate Filtering (Anti-EXPLORE / Anti-STAGNANT)
            # Only look at liquid assets with positive momentum
            if sym not in self.positions and sym not in self.cooldowns:
                if liq > self.params["min_liq"]:
                    if change24h > self.params["min_momentum"]:
                        candidates.append((sym, price, change24h))

        # 2. Logic: Manage Exits
        # Priority on exits to manage risk and free up capital.
        # We DO NOT use fixed Stop Losses (Anti-STOP_LOSS).
        # We DO NOT use time-based exits (Anti-TIME_DECAY).
        # We exit when the MARKET STRUCTURE changes.
        
        active_syms = list(self.positions.keys())
        for sym in active_syms:
            if sym not in prices: continue
            
            pos = self.positions[sym]
            current_price = float(prices[sym]["priceUsd"])
            current_chg = float(prices[sym].get("priceChange24h", 0))
            
            hist = self.history[sym]
            if len(hist) < self.params["window_slow"]: continue
            
            # Calculate Structural Trend Line
            sma_slow = statistics.mean(list(hist)[-self.params["window_slow"]:])
            
            reason = None
            
            # Exit 1: Thesis Invalidation (Momentum Flip)
            # If the asset goes red on the day, the "Bullish Trend" thesis is invalid.
            if current_chg < -0.1: 
                reason = "MOMENTUM_FLIP"
            
            # Exit 2: Structural Trend Break
            # If price closes decisively below the Slow MA, the trend is broken.
            elif current_price < sma_slow * self.params["trend_buffer"]:
                reason = "TREND_BREAK"
                
            # Exit 3: Profit Extension
            # If price extends too far above trend, capture volatility.
            elif current_price > sma_slow * 1.12: # 12% extension
                reason = "PROFIT_EXTENSION"
            
            if reason:
                qty = pos["amount"]
                del self.positions[sym]
                self.cooldowns[sym] = 25 # Cooldown to avoid wash trading
                return {
                    "side": "SELL",
                    "symbol": sym,
                    "amount": qty,
                    "reason": [reason]
                }

        # 3. Logic: Scan for Entries
        if len(self.positions) >= self.params["pos_limit"]:
            return None
            
        best_setup = None
        best_score = -float('inf')
        
        for sym, price, chg24 in candidates:
            hist = list(self.history[sym])
            if len(hist) < self.params["window_slow"]: continue
            
            # Indicators
            sma_fast = statistics.mean(hist[-self.params["window_fast"]:])
            sma_slow = statistics.mean(hist[-self.params["window_slow"]:])
            
            # Volatility (for sizing)
            vol = statistics.stdev(hist[-self.params["window_fast"]:]) if len(hist) > 5 else price * 0.01
            
            # === Trend Pullback Logic ===
            # 1. Macro Trend UP: Price > SMA Slow
            # 2. Micro Trend DIP: Price < SMA Fast
            # This avoids buying tops (Breakout penalty) and catching falling knives (Mean Reversion penalty).
            
            is_uptrend = price > sma_slow
            is_dip = price < sma_fast
            
            if is_uptrend and is_dip:
                # Scoring: Combination of Momentum Strength and Support Proximity.
                # We prefer assets moving fast (high Chg24h) that are close to support (low risk).
                
                dist_to_support = (price - sma_slow) / sma_slow 
                momentum_factor = chg24 / 100.0
                
                # Higher momentum, closer to support = Higher Score
                score = momentum_factor / (dist_to_support + 0.0001)
                
                if score > best_score:
                    best_score = score
                    
                    # Position Sizing: Risk-Based
                    # Risk is defined as distance to Structural Support (SMA Slow)
                    risk_distance = price - sma_slow
                    if risk_distance <= 0: risk_distance = price * 0.02
                    
                    risk_amt = self.balance * self.params["risk_ratio"]
                    qty = risk_amt / risk_distance
                    
                    # Cap size to 25% of balance for diversification
                    max_qty = (self.balance * 0.25) / price
                    qty = min(qty, max_qty)
                    
                    if qty > 0:
                        best_setup = (sym, qty, dist_to_support)

        # 4. Execute
        if best_setup:
            sym, qty, dist = best_setup
            
            # Record Position
            self.positions[sym] = {
                "entry": prices[sym]["priceUsd"],
                "amount": qty
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": qty,
                "reason": ["TREND_PULLBACK", f"SUP_DIST_{dist:.3f}"]
            }

        return None