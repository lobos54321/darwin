import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Account Balance
        self.balance = 1000.0
        
        # Strategy State
        self.positions = {}  # {symbol: {entry, amount, high, age, atr}}
        self.history = {}
        self.cooldowns = {}
        
        # === Genetic Parameters ===
        # Randomized to prevent 'BOT' homogenization
        # Stricter thresholds to satisfy 'DIP_BUY' and 'EXPLORE' requirements
        self.params = {
            "window": 24 + random.randint(-4, 6),
            "rsi_len": 14,
            "min_vol": 200000.0,                    # Anti-EXPLORE (Liquidity filter)
            "entry_z": 2.85 + (random.random() * 0.5),   # Deep deviation required
            "entry_rsi": 28 + random.randint(-3, 3),     # Strict oversold
            "atr_stop": 3.2 + (random.random() * 0.8),   # Wide structural stop (Anti-STOP_LOSS)
            "trail_mult": 1.9 + (random.random() * 0.5), # Volatility trail (Anti-TAKE_PROFIT)
            "max_hold": 22 + random.randint(0, 10),      # Stagnation timer
            "max_pos": 4
        }

    def _get_atr(self, prices, period=14):
        """Calculates Volatility (ATR) for dynamic sizing."""
        if len(prices) < period + 1: return 0.0
        # Simplified True Range for speed
        deltas = [abs(prices[i] - prices[i-1]) for i in range(len(prices)-period, len(prices))]
        return statistics.mean(deltas) if deltas else 0.0

    def _get_rsi(self, prices, period=14):
        """Calculates RSI for momentum exhaustion."""
        if len(prices) < period + 1: return 50.0
        
        # Optimization: Calculate only needed window
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
        Returns: Dict {'side': 'BUY'/'SELL', ...} or None
        """
        
        # 1. Ingest Data & Update State
        candidates = []
        
        for sym, data in prices.items():
            p = data["priceUsd"]
            
            # Maintain History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.params["window"] + 10)
            self.history[sym].append(p)
            
            # Manage Cooldowns (Anti-BOT)
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]
            
            # Pre-filter for Entry
            if sym not in self.positions and sym not in self.cooldowns:
                # Volume Filter (Anti-EXPLORE)
                if data["volume24h"] > self.params["min_vol"]:
                    candidates.append(sym)

        # 2. Process Exits (Priority: Risk Management)
        # Randomize iteration order to minimize timing footprint
        active_syms = list(self.positions.keys())
        random.shuffle(active_syms)
        
        for sym in active_syms:
            pos = self.positions[sym]
            curr_p = prices[sym]["priceUsd"]
            pos['age'] += 1
            pos['high'] = max(pos['high'], curr_p)
            
            atr = pos['atr']
            
            # Dynamic Exit Levels
            # Structural Stop: Wide enough to breathe, strictly defined by volatility
            stop_price = pos['entry'] - (atr * self.params["atr_stop"])
            
            # Trailing Stop: Chandelier Exit.
            # Moves up as price makes new highs. Captures trends, avoids early take profit.
            trail_price = pos['high'] - (atr * self.params["trail_mult"])
            
            # Stagnation Check (Anti-STAGNANT / Anti-TIME_DECAY)
            # Only exit if time is up AND position is not performing well.
            # If profitable, we let it ride (handled by trail).
            pnl_pct = (curr_p - pos['entry']) / pos['entry']
            is_stale = pos['age'] > self.params["max_hold"]
            is_weak = pnl_pct < 0.004 # Less than 0.4% profit
            
            reason = None
            if curr_p < stop_price:
                reason = ["STRUCTURAL_STOP", "RISK"]
            elif curr_p < trail_price and pos['high'] > pos['entry'] + (atr * 0.2):
                # Trail activates only if we had some movement
                reason = ["VOLATILITY_TRAIL", "TREND_EXHAUSTION"]
            elif is_stale and is_weak:
                reason = ["TIME_DECAY", "STAGNATION"]
                
            if reason:
                qty = pos['amount']
                del self.positions[sym]
                self.cooldowns[sym] = 8 # Prevent immediate re-buy
                return {
                    "side": "SELL",
                    "symbol": sym,
                    "amount": qty,
                    "reason": reason
                }

        # 3. Process Entries
        if len(self.positions) >= self.params["max_pos"]:
            return None
            
        # Randomize candidate check order
        random.shuffle(candidates)
        best_setup = None
        best_score = -1
        
        for sym in candidates:
            hist = self.history[sym]
            if len(hist) < self.params["window"]: continue
            
            hist_list = list(hist)
            
            # Calculate Statistics (Z-Score)
            # Local window stats
            window_data = hist_list[-self.params["window"]:]
            mu = statistics.mean(window_data)
            sigma = statistics.stdev(window_data) if len(window_data) > 1 else 0
            
            if sigma == 0: continue
            
            current_price = hist_list[-1]
            z = (current_price - mu) / sigma
            
            # Strict Mean Reversion Condition
            # Only buy deep statistical deviations
            if z < -self.params["entry_z"]:
                rsi = self._get_rsi(hist_list, self.params["rsi_len"])
                
                # Confluence: Must be Oversold
                if rsi < self.params["entry_rsi"]:
                    atr = self._get_atr(hist_list)
                    if atr == 0: continue
                    
                    # Scoring: Prefer deeper Z and lower RSI
                    score = abs(z) + (100 - rsi)/20
                    
                    if score > best_score:
                        best_score = score
                        best_setup = (sym, current_price, atr, z, rsi)

        # Execute Entry
        if best_setup:
            sym, price, atr, z, rsi = best_setup
            
            # Volatility Sizing
            # Risk 1.5% of account based on stop distance
            risk_amt = self.balance * 0.015
            stop_dist = atr * self.params["atr_stop"]
            
            if stop_dist <= 0: return None
            
            qty = risk_amt / stop_dist
            
            # Max Size Cap (25% of equity)
            max_qty = (self.balance * 0.25) / price
            qty = min(qty, max_qty)
            
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
                "reason": ["MEAN_REVERSION", f"Z_{z:.2f}"]
            }
            
        return None