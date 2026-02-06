# Darwin SDK - Agent_006 Strategy (Evolution: Phoenix Protocol v5.0)
# 🧬 Evolution: High-Frequency Momentum + Dynamic Volatility Scalping
# 🧠 Logic: "Adapt to chaos. Buy strength, sell weakness immediately."
# 🎯 Goal: Rapid recovery from drawdown using aggressive volatility capture with tight trailing stops.

import random
import math

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized: Phoenix Protocol v5.0")
        
        # --- Configuration ---
        self.min_volatility_threshold = 0.5  # Minimum % change to consider a move significant
        self.buy_threshold = 0.8             # Buy if price surges > 0.8% in one update (Momentum)
        self.trailing_stop_pct = 0.02        # 2% Trailing Stop from local high
        self.hard_stop_pct = 0.03            # 3% Hard Stop from entry (Safety net)
        self.take_profit_target = 0.10       # 10% Initial Take Profit target
        self.max_positions = 3               # Maximum number of simultaneous assets
        self.trade_allocation = 0.30         # Use 30% of balance per trade
        
        # --- State Tracking ---
        self.last_prices = {}                # {symbol: float}
        self.positions = {}                  # {symbol: {"entry": float, "high": float, "amount": float}}
        self.banned_tags = set()             # Hive Mind penalties

    def on_hive_signal(self, signal: dict):
        """Handle external signals from the Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Penalized tags received: {penalize}")
            self.banned_tags.update(penalize)
            # Immediate liquidation logic for banned tags could go here if API allowed

    def on_price_update(self, prices: dict):
        """
        Core logic loop called on every price tick (~3s).
        Decides to Buy, Sell, or Hold based on instantaneous momentum and risk rules.
        """
        decision = None
        
        # Identify current holdings based on internal state
        # In a real scenario, we would sync with wallet balance, 
        # but here we track via self.positions for strategy logic.
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Skip if data is invalid
            if current_price <= 0:
                continue

            # 1. Update History & Calculate Momentum
            last_price = self.last_prices.get(symbol, current_price)
            pct_change = ((current_price - last_price) / last_price) * 100 if last_price > 0 else 0
            self.last_prices[symbol] = current_price # Update for next tick

            # 2. Check Existing Positions (Risk Management)
            if symbol in self.positions:
                pos_data = self.positions[symbol]
                entry_price = pos_data["entry"]
                highest_price = pos_data["high"]
                
                # Update Local High (for Trailing Stop)
                if current_price > highest_price:
                    self.positions[symbol]["high"] = current_price
                    highest_price = current_price
                
                # Check Exit Conditions
                
                # A. Hard Stop Loss
                if current_price < entry_price * (1 - self.hard_stop_pct):
                    print(f"🛑 STOP LOSS triggered for {symbol}: {current_price} < {entry_price}")
                    del self.positions[symbol]
                    return {"action": "sell", "symbol": symbol, "amount": "100%"} # Sell all
                
                # B. Trailing Stop
                drawdown_from_high = (highest_price - current_price) / highest_price
                if drawdown_from_high >= self.trailing_stop_pct:
                    print(f"📉 TRAILING STOP triggered for {symbol}: Dropped {drawdown_from_high*100:.2f}% from high")
                    del self.positions[symbol]
                    return {"action": "sell", "symbol": symbol, "amount": "100%"}

                # C. Take Profit (Optional partial scale out logic could go here)
                # For now, let the trailing stop ride the winner.

            # 3. Check Entry Conditions (Opportunity Hunting)
            else:
                # Filter: Don't buy if max positions reached
                if len(self.positions) >= self.max_positions:
                    continue
                
                # Filter: Check banned tags (assuming tags are in data, otherwise skip)
                tags = data.get("tags", [])
                if any(tag in self.banned_tags for tag in tags):
                    continue

                # Strategy: Momentum Breakout
                # If price surges significantly in one tick, jump in.
                if pct_change > self.buy_threshold:
                    print(f"🚀 MOMENTUM DETECTED for {symbol}: +{pct_change:.2f}% surge")
                    
                    # Record position state
                    self.positions[symbol] = {
                        "entry": current_price,
                        "high": current_price,
                        "amount": self.trade_allocation # Logic handled by execution engine
                    }
                    
                    return {
                        "action": "buy", 
                        "symbol": symbol, 
                        "amount": self.trade_allocation
                    }
        
        return decision