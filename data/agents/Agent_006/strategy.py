# Darwin SDK - Agent_006 Strategy (Evolution: Quantum Velocity v2.1)
# 🧬 Evolution: Donchian Breakout + Volatility Gating
# 🧠 Logic: "Catch the expansion, survive the contraction."
# 🎯 Goal: High-frequency trend capture with tight trailing stops to rebuild capital.

import random
from collections import deque
from statistics import mean, stdev

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized: Quantum Velocity v2.1")
        
        # --- Configuration ---
        self.window_size = 15           # Lookback for breakout calculation
        self.volatility_window = 10     # Lookback for volatility check
        self.min_volatility = 0.002     # Minimum volatility to trade (0.2%)
        
        # --- Risk Management ---
        self.stop_loss_pct = 0.03       # Hard Stop Loss (-3%)
        self.trailing_stop_activation = 0.05 # Activate trailing stop after +5%
        self.trailing_callback = 0.02   # Trail by 2% once activated
        self.max_allocation = 0.20      # Max portfolio % per asset
        
        # --- State Tracking ---
        self.history = {}               # {symbol: deque(maxlen=window_size)}
        self.entry_prices = {}          # {symbol: float}
        self.highest_prices = {}        # {symbol: float} (for trailing stop)
        self.banned_tags = set()        # Hive Mind compliance
        self.blacklisted_symbols = set()
        self.cooldowns = {}             # {symbol: int}

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind to adapt to market sentiment"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Hive Penalty Received: {penalize}")
            self.banned_tags.update(penalize)
            
        # Immediate liquidation for penalized assets could be handled here
        # but we let the price update loop handle exits for thread safety

    def get_volatility(self, symbol):
        if len(self.history[symbol]) < 3:
            return 0.0
        return stdev(self.history[symbol]) / mean(self.history[symbol])

    def on_price_update(self, prices: dict):
        """
        Core trading logic executed on every price tick.
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # 1. Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(current_price)
            
            # Manage Cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]
                continue

            # 2. Position Management (Exit Logic)
            if symbol in self.entry_prices:
                entry_price = self.entry_prices[symbol]
                self.highest_prices[symbol] = max(self.highest_prices.get(symbol, entry_price), current_price)
                high_water_mark = self.highest_prices[symbol]
                
                # Calculate PnL percentage
                pnl_pct = (current_price - entry_price) / entry_price
                
                # A. Hard Stop Loss
                if pnl_pct <= -self.stop_loss_pct:
                    print(f"🛑 STOP LOSS triggered for {symbol} at {pnl_pct*100:.2f}%")
                    decision = {"action": "sell", "symbol": symbol, "amount": 1.0} # Sell 100%
                    self._clear_position_state(symbol)
                    self.cooldowns[symbol] = 10 # Cooldown to prevent revenge trading
                    return decision
                
                # B. Dynamic Trailing Stop
                # If we are in profit significantly, tighten the stop
                if pnl_pct >= self.trailing_stop_activation:
                    drawdown_from_high = (high_water_mark - current_price) / high_water_mark
                    if drawdown_from_high >= self.trailing_callback:
                        print(f"💰 TRAILING TAKE PROFIT for {symbol}. High: {high_water_mark}, Curr: {current_price}")
                        decision = {"action": "sell", "symbol": symbol, "amount": 1.0}
                        self._clear_position_state(symbol)
                        return decision

            # 3. Entry Logic (Donchian Channel Breakout)
            # Only buy if we don't hold it, and history is sufficient
            elif len(self.history[symbol]) == self.window_size:
                
                # Check Hive Mind Constraints
                tags = data.get("tags", [])
                if any(tag in self.banned_tags for tag in tags):
                    continue
                
                # Calculate Channel
                recent_prices = list(self.history[symbol])
                # Exclude current price from calculation to avoid look-ahead bias if update includes it
                past_prices = recent_prices[:-1] 
                
                if not past_prices: continue
                
                upper_bound = max(past_prices)
                
                # Volatility Filter: Market must be moving, not dead
                vol = self.get_volatility(symbol)
                
                # Signal: Price breaks above recent high AND volatility is healthy
                if current_price > upper_bound and vol > self.min_volatility:
                    print(f"🚀 BREAKOUT DETECTED: {symbol} broken {upper_bound} at {current_price}")
                    
                    # Position Sizing: Use fixed allocation
                    decision = {"action": "buy", "symbol": symbol, "amount": self.max_allocation}
                    
                    # Init Position State
                    self.entry_prices[symbol] = current_price
                    self.highest_prices[symbol] = current_price
                    return decision

        return decision

    def _clear_position_state(self, symbol):
        """Clean up state after selling"""
        if symbol in self.entry_prices: del self.entry_prices[symbol]
        if symbol in self.highest_prices: del self.highest_prices[symbol]