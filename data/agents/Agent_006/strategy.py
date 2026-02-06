# Darwin SDK - Agent_006 Strategy (Evolution: Lazarus Core v1.0)
# 🧬 Evolution: Trend Following + Volatility Filtering + Strict Risk Management
# 🧠 Logic: "Survive first, profit second. Filter noise, ride trends."
# 🎯 Goal: Rebuild capital by avoiding whipsaws and using Moving Average crossovers instead of raw noise.

import random
import statistics

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized: Lazarus Core v1.0")
        
        # --- Configuration ---
        self.window_short = 6          # Short-term MA window (ticks)
        self.window_long = 18          # Long-term MA window (ticks)
        self.trailing_stop_pct = 0.04  # 4% Trailing Stop (Wider to allow breathing room)
        self.take_profit_pct = 0.12    # 12% Take Profit Target
        self.max_volatility_skip = 0.05 # Skip buying if instant pump > 5% (Avoid FOMO/Slippage)
        self.max_positions = 3         # Strict limit on concurrent positions
        self.trade_allocation = 0.25   # Use 25% of balance per trade
        
        # --- State Tracking ---
        self.price_history = {}        # {symbol: [p1, p2, p3...]}
        self.positions = {}            # {symbol: {"entry": float, "high": float}}
        self.banned_tags = set()       # Penalized tags

    def on_hive_signal(self, signal: dict):
        """Absorb Hive Mind signals to avoid penalties."""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🛡️ Strategy activating shield against: {penalize}")
            self.banned_tags.update(penalize)

    def _calculate_ma(self, symbol, window):
        """Helper to calculate Moving Average safely."""
        history = self.price_history.get(symbol, [])
        if len(history) < window:
            return None
        return statistics.mean(history[-window:])

    def on_price_update(self, prices: dict):
        """
        Executed on every price update.
        Logic: Golden Cross Entry & Trailing Stop Exit.
        """
        # 1. Update Data History
        for symbol, data in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            
            current_price = data["priceUsd"]
            self.price_history[symbol].append(current_price)
            
            # Keep history buffer optimized
            if len(self.price_history[symbol]) > self.window_long + 2:
                self.price_history[symbol].pop(0)

        # 2. Evaluate Trading Decisions
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # --- EXIT LOGIC (Risk Management) ---
            if symbol in self.positions:
                pos_data = self.positions[symbol]
                
                # Update High Watermark
                if current_price > pos_data["high"]:
                    pos_data["high"] = current_price
                
                # Calculate metrics
                drawdown = (current_price - pos_data["high"]) / pos_data["high"]
                profit = (current_price - pos_data["entry"]) / pos_data["entry"]
                
                # Condition 1: Trailing Stop Hit
                if drawdown <= -self.trailing_stop_pct:
                    print(f"📉 STOP: {symbol} hit trailing stop. Closing.")
                    del self.positions[symbol]
                    return {"symbol": symbol, "action": "sell", "amount": 1.0} # Sell 100% position
                
                # Condition 2: Take Profit Hit
                if profit >= self.take_profit_pct:
                    print(f"💰 PROFIT: {symbol} reached target. Closing.")
                    del self.positions[symbol]
                    return {"symbol": symbol, "action": "sell", "amount": 1.0}

            # --- ENTRY LOGIC (Trend Following) ---
            elif len(self.positions) < self.max_positions:
                # Skip if banned
                is_banned = False
                for tag in self.banned_tags:
                    if tag in symbol: # Simple string match for tag simulation
                        is_banned = True
                        break
                if is_banned: continue

                # Calculate Indicators
                ma_short = self._calculate_ma(symbol, self.window_short)
                ma_long = self._calculate_ma(symbol, self.window_long)
                
                if ma_short and ma_long:
                    # Check for "Golden Cross" (Short MA > Long MA)
                    trend_up = ma_short > ma_long
                    price_above_ma = current_price > ma_short
                    
                    # Volatility Filter: Check last tick change
                    last_price = self.price_history[symbol][-2]
                    tick_change = (current_price - last_price) / last_price
                    safe_volatility = tick_change < self.max_volatility_skip

                    if trend_up and price_above_ma and safe_volatility:
                        print(f"🚀 ENTRY: {symbol} confirmed trend. Buying.")
                        self.positions[symbol] = {
                            "entry": current_price,
                            "high": current_price
                        }
                        return {"symbol": symbol, "action": "buy", "amount": self.trade_allocation}

        return None