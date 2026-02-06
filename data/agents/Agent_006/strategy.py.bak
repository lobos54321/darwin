```python
# Darwin SDK - Agent_006 Strategy (Evolution: Phoenix Protocol v2.1)
# 🧬 Evolution: Instant Momentum Scalping + Volatility Adaptive Stops
# 🧠 Logic: "Speed kills lag. React to velocity, not history. Cut losses instantly."
# 🎯 Goal: Aggressive recovery using high-frequency volatility capture.

import random
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized: Phoenix Protocol v2.1")
        
        # --- Configuration ---
        self.history_len = 5           # Keep very short history for immediate context
        self.buy_threshold = 1.5       # Buy if price surges > 1.5% in one tick (Aggressive)
        self.sell_drop_pct = 0.8       # Sell if price drops 0.8% from local high (Tight Trailing)
        self.max_hold_ticks = 15       # Max time to hold a position (Scalp mode)
        self.stop_loss_hard = 0.05     # 5% Hard Stop Loss
        
        # --- State Tracking ---
        self.price_history = {}        # {symbol: deque([p1, p2...], maxlen=5)}
        self.positions = {}            # {symbol: {"entry": float, "high": float, "ticks_held": int}}
        self.banned_tags = set()       # Penalized tags
        self.blacklisted_symbols = set() # Local blacklist for losing assets
        self.cooldowns = {}            # {symbol: ticks_remaining}

    def on_hive_signal(self, signal: dict):
        """Adapt to Hive Mind signals."""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Avoiding penalised tags: {penalize}")
            self.banned_tags.update(penalize)

    def on_price_update(self, prices: dict):
        """
        High-frequency decision loop.
        Called every time price updates.
        """
        decision = None
        
        # 1. Update Cooldowns
        symbols_to_clear = []
        for sym, ticks in self.cooldowns.items():
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                symbols_to_clear.append(sym)
        for sym in symbols_to_clear:
            del self.cooldowns[sym]

        # 2. Analyze Market
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Initialize history
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.history_len)
            self.price_history[symbol].append(current_price)
            
            # Manage Open Positions
            if symbol in self.positions:
                decision = self._manage_position(symbol, current_price)
                if decision:
                    return decision # Execute immediately
            else:
                # Look for Entry Opportunities if not in cooldown
                if symbol not in self.cooldowns:
                    decision = self._check_entry(symbol, current_price)
                    if decision:
                        return decision # Execute immediately

        return None

    def _check_entry(self, symbol, current_price):
        """Detect explosive momentum."""
        # Check blacklist/bans
        if symbol in self.blacklisted_symbols:
            return None
            
        history = self.price_history[symbol]
        if len(history) < 2:
            return None
            
        prev_price = history[-2]
        
        # Calculate instant change (Velocity)
        pct_change = ((current_price - prev_price) / prev_price) * 100
        
        # ENTRY LOGIC: High Momentum Breakout
        # If price jumps significantly in one tick, ride the wave.
        if pct_change > self.buy_threshold:
            # Check for exhaustion: Don't buy if we are already up > 20% in last 5 ticks
            if len(history) >= 5:
                total_pump = ((current_price - history[0]) / history[0]) * 100
                if total_pump > 20.0: 
                    return None
            
            print(f"🚀 BUY SIGNAL: {symbol} surged {pct_change:.2f}%")
            self.positions[symbol] = {
                "entry": current_price,
                "high": current_price,
                "ticks_held": 0
            }
            # Aggressive allocation to recover losses
            return {"action": "buy", "symbol": symbol, "amount": "98%"} 

        return None

    def _manage_position(self, symbol, current_price):
        """Manage exits with trailing stops and time limits."""
        pos = self.positions[symbol]
        pos["ticks_held"] += 1
        
        # Update High Watermark
        if current_price > pos["high"]:
            pos["high"] = current_price
            
        # Calculate PnL stats
        entry_price = pos["entry"]
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        drawdown_from_high = ((pos["high"] - current_price) / pos["high"]) * 100
        
        should_sell = False
        reason = ""
        
        # 1. Trailing Stop (Protect Profits)
        if pnl_pct > 2.0 and drawdown_from_high > self.sell_drop_pct:
            should_sell = True
            reason = f"Trailing Stop (Locked Profit)"
            
        # 2. Quick Cut (If momentum fails immediately)
        elif pos["ticks_held"] < 3 and pnl_pct < -1.0:
            should_sell = True
            reason = "Failed Breakout"
            
        # 3. Hard Stop Loss
        elif pnl_pct < -self.stop_loss_hard * 100:
            should_sell = True
            reason = "Hard Stop Loss"
            self.blacklisted_symbols.add(symbol) # Ban toxic asset
            
        # 4. Time Decay (Don't hold stagnant assets)
        elif pos["ticks_held"] > self.max_hold_ticks and pnl_pct < 1.0:
            should_sell = True
            reason = "Stagnation"
            
        if should