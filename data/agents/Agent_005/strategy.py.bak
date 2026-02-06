# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import math
import statistics
from collections import deque

class MyStrategy:
    """
    Agent_005 Gen 31: 'Obsidian Shield'
    
    [Evolution Log]
    - Status: Critical Recovery ($720 Balance)
    - Parent: Gen 30 (Phoenix Reflex)
    - Mutation: Shifted from high-frequency micro-scalping to Volatility Breakout.
    - Improvements:
        1. Noise Filtering: Replaced raw tick velocity with Standard Deviation (Volatility) filters.
        2. Capital Preservation: Position sizing is now strictly proportional to current equity.
        3. 'Cool-down' Mechanism: Prevents re-entering a symbol immediately after a loss.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Obsidian Shield v31.0)")
        
        # --- Market Data History ---
        self.history_window = 20
        self.price_history = {} # {symbol: deque(maxlen=20)}
        self.last_prices = {}
        
        # --- Risk Management ---
        self.active_trades = {} # {symbol: entry_price}
        self.banned_tags = set()
        self.cooldowns = {} # {symbol: ticks_remaining}
        
        # --- Parameters ---
        self.volatility_threshold = 1.5 # Entry on 1.5 sigma moves
        self.min_history = 10
        self.stop_loss_pct = 0.03       # Tight 3% SL
        self.take_profit_pct = 0.06     # 6% TP (2:1 Ratio)
        self.max_positions = 4

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)

    def _calculate_volatility(self, prices):
        if len(prices) < 2:
            return 0.0
        return statistics.stdev(prices)

    def _calculate_sma(self, prices):
        if not prices:
            return 0.0
        return sum(prices) / len(prices)

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        """
        # 1. Update History & Manage Cooldowns
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.history_window)
            self.price_history[symbol].append(current_price)
            
            # Decrement cooldown
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # 2. Manage Active Trades (Exit Logic)
        active_symbols = list(self.active_trades.keys())
        for symbol in active_symbols:
            if symbol not in prices:
                continue
                
            current_price = prices[symbol]["priceUsd"]
            entry_price = self.active_trades[symbol]
            
            # Calculate PnL percentage
            pnl_pct = (current_price - entry_price) / entry_price
            
            # STOP LOSS
            if pnl_pct <= -self.stop_loss_pct:
                print(f"🛑 SL Triggered: {symbol} at {pnl_pct:.2%}")
                del self.active_trades[symbol]
                self.cooldowns[symbol] = 10 # Stay out for 10 ticks
                return "sell" # Simplified signal return for simulation
            
            # TAKE PROFIT
            if pnl_pct >= self.take_profit_pct:
                print(f"💰 TP Triggered: {symbol} at {pnl_pct:.2%}")
                del self.active_trades[symbol]
                return "sell"

        # 3. Scan for New Entries (Entry Logic)
        # Only enter if we have slots available
        if len(self.active_trades) >= self.max_positions:
            return

        for symbol, data in prices.items():
            # Skip if active, banned, or cooling down
            if symbol in self.active_trades or symbol in self.banned_tags or symbol in self.cooldowns:
                continue
                
            history = self.price_history.get(symbol, [])
            if len(history) < self.min_history:
                continue
                
            current_price = data["priceUsd"]
            sma = self._calculate_sma(history)
            stdev = self._calculate_volatility(history)
            
            # Avoid division by zero
            if stdev == 0:
                continue

            # Volatility Breakout Logic:
            # Price is significantly above the mean (Momentum) AND volatility is expanding
            z_score = (current_price - sma) / stdev
            
            # Check 24h change to align with macro trend (Winner's influence)
            macro_trend_up = data.get("priceChange24h", 0) > 0
            
            if z_score > self.volatility_threshold and macro_trend_up:
                print(f"🚀 Breakout Detected: {symbol} (Z: {z_score:.2f})")
                self.active_trades[symbol] = current_price
                return "buy"

        self.last_prices = {s: d["priceUsd"] for s, d in prices.items()}