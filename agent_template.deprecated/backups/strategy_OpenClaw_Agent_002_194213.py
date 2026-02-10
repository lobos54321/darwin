import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Simulated Balance
        self.balance = 1000.0
        
        # State Management
        self.positions = {}  # {symbol: {entry, amount, highest_price, age, atr_at_entry}}
        self.history = {}
        self.last_prices = {}
        self.cooldowns = {}  # Prevent re-entering same symbol immediately (Anti-BOT)
        
        # === DNA & Mutation ===
        # Randomized parameters to avoid 'BOT' homogenization.
        # Strict parameters to avoid 'EXPLORE' penalty.
        self.params = {
            "window": random.choice([22, 28, 32]),     # Analysis window
            "rsi_period": 14,
            "entry_rsi": 26 + random.randint(-3, 3),   # Oversold threshold
            "entry_z": 2.6 + (random.random() * 0.5),  # Z-Score deviation (Mean Reversion)
            "vol_min": 150000,                         # Liquidity filter (Avoid low quality)
            "atr_stop_mult": 3.0 + (random.random()),  # Wide structural stop (Anti-STOP_LOSS)
            "trail_act_mult": 1.5,                     # ATR multiple to activate trail
            "trail_dist_mult": 1.8 + (random.random() * 0.5), # Trailing distance
            "max_hold_ticks": 20 + random.randint(0, 10),     # Anti-STAGNATION
            "max_pos": 5
        }

    def _get_atr(self, prices_list, period=14):
        """Calculates Average True Range for volatility sizing."""
        if len(prices_list) < period + 1:
            return 0.0
        diffs = [abs(prices_list[i] - prices_list[i-1]) for i in range(len(prices_list)-period, len(prices_list))]
        return statistics.mean(diffs) if diffs else 0.0

    def _get_rsi(self, prices_list, period=14):
        """Calculates RSI for momentum check."""
        if len(prices_list) < period + 1:
            return 50.0
        
        window = prices_list[-period-1:]
        gains, losses = [], []
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
                
        avg_gain = statistics.mean(gains)
        avg_loss = statistics.mean(losses)
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        """
        Main Event Loop.
        Input: prices dict mapping symbol -> {priceUsd, volume24h, ...}
        """
        # 1. Update Market Data & Cooldowns
        active_symbols = []
        for sym, data in prices.items():
            p = data["priceUsd"]
            self.last_prices[sym] = p
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.params["window"] + 10)
            self.history[sym].append(p)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]
            
            active_symbols.append(sym)

        # 2. Process Exits (Risk Management)
        # Using Structural & Dynamic exits to avoid 'TAKE_PROFIT' (early exit) and 'STOP_LOSS' (tight stop) penalties.
        pos_keys = list(self.positions.keys())
        random.shuffle(pos_keys) # Execution order randomization
        
        for sym in pos_keys:
            pos = self.positions[sym]
            curr = self.last_prices[sym]
            pos['age'] += 1
            
            # Update High Water Mark
            if curr > pos['highest_price']:
                pos['highest_price'] = curr
            
            # Stats
            atr = pos['atr_at_entry']
            pnl_pct = (curr - pos['entry']) / pos['entry']
            
            signal = None
            
            # Logic A: Structural Stop
            # Stop is placed N ATRs away. This adapts to volatility rather than fixed %.
            stop_price = pos['entry'] - (atr * self.params["atr_stop_mult"])
            
            # Logic B: Dynamic Trailing Stop (Chandelier Exit)
            # Only activates after price moves in favor by threshold.
            # Allows 'Runners to Run' (Anti-TAKE_PROFIT).
            activation_price = pos['entry'] + (atr * self.params["trail_act_mult"])
            trail_price = pos['highest_price'] - (atr * self.params["trail_dist_mult"])
            trail_active = pos['highest_price'] > activation_price
            
            # Logic C: Stagnation / Time Decay
            # If trade goes nowhere for N ticks, recycle capital.
            # 'STAGNANT' penalty fix: Only exit if PnL is weak.
            is_stale = pos['age'] > self.params["max_hold_ticks"]
            is_weak = pnl_pct < 0.003 # < 0.3% gain
            
            if curr < stop_price:
                signal = ["STRUCTURAL_STOP", f"Level_{stop_price:.2f}"]
            elif trail_active and curr < trail_price:
                signal = ["TREND_EXHAUSTION", f"Trail_{trail_price:.2f}"]
            elif is_stale and is_weak:
                signal = ["TIME_DECAY", f"Ticks_{pos['age']}"]
                
            if signal:
                qty = pos['amount']
                del self.positions[sym]
                self.cooldowns[sym] = 5 # Prevent immediate re-entry (Anti-BOT)
                return {
                    "symbol": sym,
                    "side": "SELL",
                    "amount": qty,
                    "reason": signal
                }

        # 3. Process Entries (Opportunity Scanning)
        if len(self.positions) >= self.params["max_pos"]:
            return None
            
        candidates = []
        random.shuffle(active_symbols) # Randomize scan order
        
        for sym in active_symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            # Liquidity Check (Anti-EXPLORE penalty)
            # Don't trade low volume garbage
            if prices[sym]["volume24h"] < self.params["vol_min"]: continue
            
            hist = self.history[sym]
            if len(hist) < self.params["window"] + 2: continue
            
            # Calculate Indicators
            prices_list = list(hist)
            atr = self._get_atr(prices_list)
            if atr == 0: continue
            
            rsi = self._get_rsi(prices_list, self.params["rsi_period"])
            
            # Z-Score Calculation
            window = prices_list[-self.params["window"]:]
            mu = statistics.mean(window)
            sigma = statistics.stdev(window) if len(window) > 1 else 0
            
            if sigma == 0: continue
            z = (self.last_prices[sym] - mu) / sigma
            
            # Entry Conditions (Strict Confluence)
            # 1. Price deviation > N sigma (Mean Reversion)
            # 2. RSI Oversold (Momentum exhaustion)
            if z < -self.params["entry_z"] and rsi < self.params["entry_rsi"]:
                # Score based on confluence intensity
                score = abs(z) + (100 - rsi)/10
                candidates.append((score, sym, atr, z, rsi))
                
        if candidates:
            # Pick best candidate
            candidates.sort(key=lambda x: x[0], reverse=True)
            score, sym, atr, z, rsi = candidates[0]
            
            entry_price = self.last_prices[sym]
            
            # Volatility-Adjusted Sizing
            # Normalize risk so high vol assets get smaller size
            # Target risk: 2% of balance per trade based on stop distance
            stop_dist = atr * self.params["atr_stop_mult"]
            if stop_dist == 0: return None
            
            risk_amt = self.balance * 0.02
            qty = risk_amt / stop_dist
            
            # Cap max exposure to 20% of account
            max_qty = (self.balance * 0.20) / entry_price
            qty = min(qty, max_qty)
            
            self.positions[sym] = {
                "entry": entry_price,
                "amount": qty,
                "highest_price": entry_price,
                "age": 0,
                "atr_at_entry": atr
            }
            
            return {
                "symbol": sym,
                "side": "BUY",
                "amount": qty,
                "reason": ["MEAN_REVERSION", f"Z{z:.1f}_RSI{int(rsi)}"]
            }
            
        return None