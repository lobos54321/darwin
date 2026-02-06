# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import statistics
from collections import deque

class MyStrategy:
    """
    Agent: Contrarian_239 -> Evolved: Kinetic_Breakout_v3
    
    🧬 Evolution Summary:
    1.  **Pivot from Mean Reversion**: Abandoned the failed 'buy the dip' (Z-Score) logic which caused the -46% loss in trending markets.
    2.  **Adopted Winner's DNA (Momentum)**: Implemented a 'Trend Filter' using 24h change. We now only trade assets that are already proving themselves winners.
    3.  **Mutation (Volatility Breakout)**: Instead of simple moving averages, we use a Short-Term Volatility Breakout logic. We buy when price velocity accelerates.
    4.  **Risk Management (Trailing Stop)**: Replaced fixed targets with a dynamic Trailing Stop to let winners run while cutting losers immediately.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Kinetic_Breakout_v3)")
        
        # --- Configuration ---
        self.HISTORY_LEN = 20           # Keep last 20 ticks for calculation
        self.MOMENTUM_WINDOW = 5        # Calculate velocity over last 5 ticks
        self.VELOCITY_THRESHOLD = 0.002 # 0.2% move in window = breakout
        
        # --- Risk Management ---
        self.TRAILING_STOP_PCT = 0.015  # 1.5% trailing stop (tight)
        self.HARD_STOP_PCT = 0.03       # 3% hard stop (emergency)
        self.MAX_POSITION_SIZE = 100    # Max USD per trade
        
        # --- State ---
        self.history = {}               # {symbol: deque([prices])}
        self.positions = {}             # {symbol: {entry_price, highest_price, amount}}
        self.banned_tags = set()
        self.last_prices = {}

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)

    def on_price_update(self, prices: dict):
        """
        Main Trading Logic Loop
        Returns: ('BUY'/'SELL', symbol, amount) or None
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            pct_change_24h = data.get("priceChange24h", 0)
            
            # 1. Initialize History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.HISTORY_LEN)
            self.history[symbol].append(current_price)
            
            # 2. Manage Existing Position (Exit Logic)
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Update High Water Mark
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
                
                # Calculate Drawdown from High
                drawdown = (pos['highest_price'] - current_price) / pos['highest_price']
                
                # Calculate Absolute Loss from Entry
                absolute_loss = (pos['entry_price'] - current_price) / pos['entry_price']
                
                # A. Trailing Stop Hit
                if drawdown >= self.TRAILING_STOP_PCT:
                    print(f"📉 {symbol}: Trailing Stop Hit. High: {pos['highest_price']}, Curr: {current_price}")
                    decision = ("SELL", symbol, pos['amount'])
                    del self.positions[symbol]
                    break # Execute one action per tick
                
                # B. Hard Stop Hit
                if absolute_loss >= self.HARD_STOP_PCT:
                    print(f"🛑 {symbol}: Hard Stop Hit. Entry: {pos['entry_price']}, Curr: {current_price}")
                    decision = ("SELL", symbol, pos['amount'])
                    del self.positions[symbol]
                    break
                    
            # 3. Look for Entries (Momentum Logic)
            else:
                # Filter 1: Global Trend (Winner's Wisdom)
                # Only look at coins that are positive on the day
                if pct_change_24h < 0.5: 
                    continue
                
                # Filter 2: Sufficient Data
                if len(self.history[symbol]) < self.HISTORY_LEN:
                    continue
                    
                # Filter 3: Local Velocity (Mutation)
                # Compare current price to price N ticks ago
                past_price = self.history[symbol][-self.MOMENTUM_WINDOW]
                velocity = (current_price - past_price) / past_price
                
                # Filter 4: Volatility Check (Avoid flat markets)
                recent_prices = list(self.history[symbol])
                stdev = statistics.stdev(recent_prices) if len(recent_prices) > 1 else 0
                mean = statistics.mean(recent_prices)
                cv = stdev / mean if mean > 0 else 0
                
                # ENTRY TRIGGER: High Velocity + Moderate Volatility
                if velocity > self.VELOCITY_THRESHOLD and cv > 0.0005:
                    amount_to_buy = self.MAX_POSITION_SIZE / current_price
                    
                    self.positions[symbol] = {
                        'entry_price': current_price,
                        'highest_price': current_price,
                        'amount': amount_to_buy
                    }
                    print(f"🚀 {symbol}: Momentum Breakout! Vel: {velocity:.4f}, 24h: {pct_change_24h}%")
                    decision = ("BUY", symbol, amount_to_buy)
                    break 

            self.last_prices[symbol] = current_price

        return decision