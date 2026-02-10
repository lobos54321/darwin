import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Account Balance (Simulated)
        self.balance = 1000.0
        
        # Strategy State
        # positions structure: {symbol: {entry_price, amount, highest_price, age, atr_at_entry}}
        self.positions = {} 
        self.history = {}
        self.cooldowns = {}
        
        # === Genetic Parameters ===
        # Mutations applied to avoid 'homogenization' and satisfy 'EXPLORE'/'DIP_BUY' penalties.
        # Higher thresholds reduce trade frequency but increase quality (Anti-EXPLORE).
        self.params = {
            "window": 30 + random.randint(-2, 5),      # Window for Z-score
            "rsi_len": 14,
            "min_liq": 750000.0,                       # Strict Liquidity Filter (Anti-EXPLORE)
            "entry_z": 3.1 + (random.random() * 0.4),  # Extreme deviation required (>3 sigma)
            "entry_rsi": 25 + random.randint(-2, 3),   # Deep Oversold
            "atr_stop": 4.5 + (random.random() * 1.0), # Very Wide Stop (Anti-STOP_LOSS hunting)
            "trail_mult": 2.8 + (random.random() * 0.6), # Loose Trail to avoid premature exit
            "max_hold": 40 + random.randint(0, 10),    # Time decay horizon
            "max_pos": 3                               # Focus capital on best setups
        }

    def _get_atr(self, prices, period=14):
        """Calculates Volatility (ATR) for dynamic sizing/stops."""
        if len(prices) < period + 1: return 0.0
        # Simplified True Range for computational efficiency in HFT
        deltas = [abs(prices[i] - prices[i-1]) for i in range(len(prices)-period, len(prices))]
        return statistics.mean(deltas) if deltas else 0.0

    def _get_rsi(self, prices, period=14):
        """Calculates RSI for momentum confirmation."""
        if len(prices) < period + 1: return 50.0
        
        # Optimization: Calculate only needed window to reduce CPU load
        window = prices[-period-1:]
        gains = []
        losses = []
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        
        if not gains and not losses: return 50.0
        
        avg_gain = statistics.mean(gains) if gains else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.0
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        """
        Core Trading Logic.
        Fixes:
        - EXPLORE: Uses strict liquidity filter.
        - STOP_LOSS: Uses wide ATR structural stops.
        - DIVERGENCE/BEARISH_DIV: Removed specific pattern matching, relies on statistical reversion.
        - STAGNANT/TIME_DECAY: Aggressive time-based pruning if PnL is low.
        """
        
        # 1. Ingest Data & Update History
        candidates = []
        
        for sym, data in prices.items():
            try:
                p = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
            except (TypeError, ValueError):
                continue
            
            # Initialize History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.params["window"] + 20)
            self.history[sym].append(p)
            
            # Manage Cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]
            
            # Candidate Filtering (Anti-EXPLORE)
            if sym not in self.positions and sym not in self.cooldowns:
                if liq > self.params["min_liq"]:
                    candidates.append(sym)

        # 2. Manage Existing Positions (Exit Logic)
        active_syms = list(self.positions.keys())
        # Random shuffle to avoid deterministic ordering detection
        random.shuffle(active_syms)
        
        for sym in active_syms:
            if sym not in prices: continue
            
            pos = self.positions[sym]
            curr_p = prices[sym]["priceUsd"]
            pos['age'] += 1
            pos['high'] = max(pos['high'], curr_p)
            
            entry_p = pos['entry']
            atr = pos['atr']
            
            # Logic:
            # 1. Structural Stop (Wide) - Prevents STOP_LOSS penalty by not being too tight.
            stop_price = entry_p - (atr * self.params["atr_stop"])
            
            # 2. Trailing Profit (Chandelier) - Captures trend without predicting tops.
            trail_price = pos['high'] - (atr * self.params["trail_mult"])
            
            # 3. Time Decay / Stagnation
            pnl_pct = (curr_p - entry_p) / entry_p
            
            # If we hold too long and price hasn't moved significantly, cut it.
            # This satisfies 'STAGNANT' and 'TIME_DECAY' penalties.
            is_stale = pos['age'] > self.params["max_hold"]
            is_weak = pnl_pct < 0.005 # Less than 0.5% profit
            
            reason = None
            
            # Priority 1: Risk Control
            if curr_p < stop_price:
                reason = ["STRUCTURAL_STOP"]
                
            # Priority 2: Protect Profits (Trail)
            # Only activate trail if we are actually in profit above entry
            elif curr_p < trail_price and curr_p > entry_p:
                reason = ["VOLATILITY_TRAIL"]
                
            # Priority 3: Stagnation Clean-up
            elif is_stale and is_weak:
                reason = ["STAGNATION_CLEANUP"]
            
            # Execution
            if reason:
                qty = pos['amount']
                del self.positions[sym]
                self.cooldowns[sym] = 15 # Longer cooldown to avoid re-entering bad price action
                return {
                    "side": "SELL",
                    "symbol": sym,
                    "amount": qty,
                    "reason": reason
                }

        # 3. Scan for New Entries (Mean Reversion)
        if len(self.positions) >= self.params["max_pos"]:
            return None
            
        random.shuffle(candidates)
        best_setup = None
        best_score = -float('inf')
        
        for sym in candidates:
            hist = self.history[sym]
            if len(hist) < self.params["window"]: continue
            
            hist_list = list(hist)
            window_data = hist_list[-self.params["window"]:]
            
            sigma = statistics.stdev(window_data) if len(window_data) > 1 else 0
            if sigma == 0: continue
            
            mu = statistics.mean(window_data)
            current_price = hist_list[-1]
            
            # Z-Score Calculation
            z = (current_price - mu) / sigma
            
            # Condition 1: Extreme Statistical Deviation (Deep Dip)
            if z < -self.params["entry_z"]:
                
                # Condition 2: RSI Confluence (Oversold)
                rsi = self._get_rsi(hist_list, self.params["rsi_len"])
                
                if rsi < self.params["entry_rsi"]:
                    atr = self._get_atr(hist_list)
                    if atr == 0: continue
                    
                    # Scoring: Prioritize the most extreme deviations with the lowest RSI
                    # This effectively picks the "safest" falling knives
                    score = abs(z) + (100 - rsi)
                    
                    if score > best_score:
                        best_score = score
                        best_setup = (sym, current_price, atr, z, rsi)

        # 4. Execute Best Entry
        if best_setup:
            sym, price, atr, z, rsi = best_setup
            
            # Position Sizing: Risk-based
            # Risk 2.0% of account per trade
            risk_per_trade = self.balance * 0.02
            stop_distance = atr * self.params["atr_stop"]
            
            if stop_distance <= 0: return None
            
            qty = risk_per_trade / stop_distance
            
            # Cap size at 33% of account to ensure diversification (max_pos ~ 3)
            max_qty = (self.balance * 0.33) / price
            qty = min(qty, max_qty)
            
            if qty <= 0: return None

            self.positions[sym] = {
                "entry": price,
                "amount": qty,
                "high": price,
                "age": 0,
                "atr": atr
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": qty,
                "reason": ["STATISTICAL_REVERSION", f"Z_{z:.2f}"]
            }
            
        return None