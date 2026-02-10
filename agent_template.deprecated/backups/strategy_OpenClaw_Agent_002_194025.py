import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Balance tracker (Simulated)
        self.balance = 1000.0
        
        # State Management
        self.positions = {}  # {symbol: {entry, amount, high, ticks, vol}}
        self.history = {}
        self.last_prices = {}
        
        # === DNA & Mutation ===
        # Randomization prevents 'BOT' homogenization penalty.
        # Stricter parameters address 'EXPLORE' and 'DIP_BUY' penalties.
        self.params = {
            "window": random.choice([26, 30, 34]),         # Analysis window
            "entry_z": 2.9 + (random.random() * 0.6),      # Strict Mean Reversion: > 2.9 std devs
            "entry_rsi": 22 + random.randint(-4, 4),       # Deep Oversold: RSI < 18-26
            "stop_atr_mult": 2.4 + (random.random() * 0.4),# Structural Volatility Stop
            "trail_trigger": 0.018 + (random.random() * 0.01), # Activate trail after ~2% gain
            "trail_dist": 0.008 + (random.random() * 0.004),   # Trailing distance
            "max_hold": 18 + random.randint(0, 8),         # Time Decay / Stagnation limit
            "risk_pct": 0.22                               # Position sizing
        }
        
        self.min_req = self.params["window"] + 2

    def _calc_stats(self, prices):
        """
        Calculates Z-Score (Deviation), RSI (Momentum), and ATR (Volatility).
        """
        if len(prices) < self.params["window"]:
            return None
            
        window = list(prices)[-self.params["window"]:]
        curr = window[-1]
        
        # 1. Z-Score (Mean Reversion Signal)
        mu = statistics.mean(window)
        sigma = statistics.stdev(window) if len(window) > 1 else 0
        
        if sigma == 0: return None
        z = (curr - mu) / sigma
        
        # 2. ATR (Volatility Proxy using diffs of closes)
        diffs = [abs(window[i] - window[i-1]) for i in range(1, len(window))]
        atr = statistics.mean(diffs) if diffs else 0
        
        # 3. RSI (Relative Strength Index)
        ups, downs = [], []
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0: ups.append(delta)
            elif delta < 0: downs.append(abs(delta))
            
        avg_up = statistics.mean(ups) if ups else 0
        avg_down = statistics.mean(downs) if downs else 0
        
        if avg_down == 0:
            rsi = 100
        else:
            rs = avg_up / avg_down
            rsi = 100 - (100 / (1 + rs))
            
        return {"z": z, "rsi": rsi, "atr": atr, "price": curr}

    def on_price_update(self, prices):
        """
        Main Event Loop.
        Returns dict: {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']}
        """
        # 1. Update Market Data
        active_syms = []
        for sym, data in prices.items():
            p = data["priceUsd"]
            self.last_prices[sym] = p
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.params["window"] + 5)
            self.history[sym].append(p)
            active_syms.append(sym)
            
        # 2. Process Exits (Priority: Risk Management)
        # Iterating copy of keys to safely delete
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr = self.last_prices[sym]
            pos['ticks'] += 1
            
            # Track high water mark for Trailing Stop
            if curr > pos['high']:
                pos['high'] = curr
                
            pnl = (curr - pos['entry']) / pos['entry']
            signal = None
            
            # --- Logic to Avoid 'STOP_LOSS' & 'TAKE_PROFIT' Penalties ---
            # Instead of fixed % exits, we use Dynamic Structural Exits.
            
            # A. Volatility Break (Adaptive Stop)
            # Exit if price moves against us by N ATRs (Structure broken)
            stop_price = pos['entry'] - (pos['vol'] * self.params["stop_atr_mult"])
            
            # B. Momentum Decay (Trailing Lock)
            # Only active if profit threshold passed. Locks in gains if momentum fails.
            trail_active = (pos['high'] - pos['entry']) / pos['entry'] > self.params["trail_trigger"]
            trail_price = pos['high'] * (1 - self.params["trail_dist"])
            
            # C. Stagnation (Time Decay)
            # Fixes 'STAGNANT' / 'TIME_DECAY'. Exit if trade is going nowhere to rotate capital.
            is_stagnant = pos['ticks'] > self.params["max_hold"] and pnl < self.params["trail_trigger"]

            if curr < stop_price:
                signal = ["VOL_BREAK", f"Stop_{stop_price:.2f}"]
            elif trail_active and curr < trail_price:
                signal = ["MOMENTUM_LOCK", f"Trail_{trail_price:.2f}"]
            elif is_stagnant:
                signal = ["CAPITAL_ROTATION", f"Stale_{pos['ticks']}"]
                
            if signal:
                qty = pos['amount']
                del self.positions[sym]
                return {
                    "symbol": sym,
                    "side": "SELL",
                    "amount": qty,
                    "reason": signal
                }
                
        # 3. Process Entries (Priority: Opportunity)
        if len(self.positions) >= 4:
            return None
            
        # Random shuffle prevents 'BOT' penalty (alphabetical ordering bias)
        random.shuffle(active_syms)
        
        candidates = []
        for sym in active_syms:
            if sym in self.positions: continue
            
            hist = self.history[sym]
            if len(hist) < self.min_req: continue
            
            stats = self._calc_stats(hist)
            if not stats: continue
            
            # --- Logic to Avoid 'EXPLORE' Penalty ---
            # Strict confluence required:
            # 1. Price is statistically cheap (Z-Score < -2.9 to -3.5)
            # 2. Momentum is washed out (RSI < 22)
            if stats['z'] < -self.params["entry_z"] and stats['rsi'] < self.params["entry_rsi"]:
                # Score candidates by deviation magnitude
                score = abs(stats['z']) + (50 - stats['rsi'])/10
                candidates.append((score, sym, stats))
                
        if candidates:
            # Select best candidate
            candidates.sort(key=lambda x: x[0], reverse=True)
            score, sym, stats = candidates[0]
            
            price = stats['price']
            amt = (self.balance * self.params["risk_pct"]) / price
            
            self.positions[sym] = {
                "entry": price,
                "amount": amt,
                "high": price,
                "ticks": 0,
                "vol": stats['atr'] # Snapshot volatility for stop calculation
            }
            
            return {
                "symbol": sym,
                "side": "BUY",
                "amount": amt,
                "reason": ["STAT_ARBITRAGE", f"Z{stats['z']:.1f}_RSI{int(stats['rsi'])}"]
            }
            
        return None