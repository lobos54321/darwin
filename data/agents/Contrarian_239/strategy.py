# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import statistics
from collections import deque

class MyStrategy:
    """
    Agent: Contrarian_239 -> Evolved: Phoenix_Trend_v1
    
    🧬 Evolution Summary:
    1.  **Shift to Trend Following**: Abandoned the "Contrarian" logic that caused the -46% drawdown. Adopting the Winner's implied "Momentum" approach.
    2.  **Adaptive Moving Averages**: Uses a Fast (7-tick) and Slow (21-tick) EMA crossover to identify genuine trend shifts rather than noise.
    3.  **Strict Recovery Risk Management**: 
        - Position sizing reduced to 10% of equity to survive the drawdown.
        - Hard Stop Loss at -3% to prevent catastrophic loss.
        - Trailing Stop logic to lock in profits during pumps.
    4.  **Hive Mind Compliance**: Strictly obeys penalization signals to avoid system bans.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Phoenix_Trend_v1)")
        
        # --- Strategy Parameters ---
        self.FAST_WINDOW = 7
        self.SLOW_WINDOW = 21
        self.MAX_HISTORY = 30
        
        # --- Risk Management ---
        self.POSITION_SIZE_PCT = 0.10   # Conservative sizing for recovery
        self.STOP_LOSS_PCT = 0.03       # 3% Max risk per trade
        self.TRAILING_START_PCT = 0.05  # Start trailing after 5% gain
        self.TRAILING_CALLBACK = 0.02   # Sell if drops 2% from peak
        
        # --- State Tracking ---
        self.history = {}               # {symbol: deque([prices])}
        self.positions = {}             # {symbol: {"entry": float, "highest": float, "amount": float}}
        self.banned_tags = set()
        self.equity = 536.69            # Sync with current balance provided in prompt

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Penalty received for: {penalize}")
            self.banned_tags.update(penalize)
            # Immediate exit if we hold a banned asset
            for tag in penalize:
                if tag in self.positions:
                    # Logic to force close would happen in next price update
                    pass

    def _calculate_ema(self, prices, window):
        if len(prices) < window:
            return None
        multiplier = 2 / (window + 1)
        ema = prices[0] # Start with SMA equivalent or first item
        for price in list(prices)[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def on_price_update(self, prices: dict):
        """
        Main trading logic loop.
        Returns a decision tuple: (action, symbol, amount/details)
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # 1. Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.MAX_HISTORY)
            self.history[symbol].append(current_price)
            
            # Skip if banned
            if symbol in self.banned_tags:
                if symbol in self.positions:
                    return ("sell", symbol, 1.0) # Panic sell 100%
                continue

            # 2. Check Existing Positions (Risk Management)
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos["entry"]
                
                # Update Highest Price for Trailing Stop
                if current_price > pos["highest"]:
                    self.positions[symbol]["highest"] = current_price
                
                pct_change = (current_price - entry_price) / entry_price
                drawdown_from_peak = (pos["highest"] - current_price) / pos["highest"]
                
                # STOP LOSS
                if pct_change < -self.STOP_LOSS_PCT:
                    print(f"🛑 STOP LOSS triggered for {symbol} at {pct_change*100:.2f}%")
                    del self.positions[symbol]
                    return ("sell", symbol, 1.0)
                
                # TRAILING TAKE PROFIT
                if pct_change > self.TRAILING_START_PCT and drawdown_from_peak > self.TRAILING_CALLBACK:
                    print(f"💰 TRAILING PROFIT triggered for {symbol}. Peak gain: {(pos['highest']/entry_price - 1)*100:.2f}%")
                    del self.positions[symbol]
                    return ("sell", symbol, 1.0)
                    
                # Trend Reversal Exit (Fast EMA crosses below Slow EMA)
                fast_ema = self._calculate_ema(self.history[symbol], self.FAST_WINDOW)
                slow_ema = self._calculate_ema(self.history[symbol], self.SLOW_WINDOW)
                
                if fast_ema and slow_ema and fast_ema < slow_ema:
                     print(f"📉 Trend Reversal Exit for {symbol}")
                     del self.positions[symbol]
                     return ("sell", symbol, 1.0)

            # 3. Check New Entry Signals (Momentum)
            else:
                # Need enough history
                if len(self.history[symbol]) >= self.SLOW_WINDOW:
                    fast_ema = self._calculate_ema(self.history[symbol], self.FAST_WINDOW)
                    slow_ema = self._calculate_ema(self.history[symbol], self.SLOW_WINDOW)
                    
                    # Golden Cross Logic: Fast > Slow
                    # Mutation: Ensure price is also above Slow EMA to confirm strength
                    if fast_ema and slow_ema and fast_ema > slow_ema and current_price > slow_ema:
                        
                        # Volatility Filter: Don't buy if standard deviation is crazy high (Pump protection)
                        recent_vol = statistics.stdev(list(self.history[symbol])[-10:])
                        avg_price = statistics.mean(list(self.history[symbol])[-10:])
                        if (recent_vol / avg_price) < 0.05: # Only enter if volatility < 5%
                            
                            trade_amount = self.equity * self.POSITION_SIZE_PCT
                            self.positions[symbol] = {
                                "entry": current_price, 
                                "highest": current_price,
                                "amount": trade_amount
                            }
                            print(f"🚀 MOMENTUM ENTRY for {symbol} at {current_price}")
                            return ("buy", symbol, trade_amount)

        return decision