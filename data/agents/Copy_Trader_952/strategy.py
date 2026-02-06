import math
import statistics
from collections import deque, defaultdict

class MyStrategy:
    """
    Agent: Copy_Trader_952 (Gen 6 - Phoenix Breakout)
    Evolutionary Logic:
    1.  Mutation: Abandoned lagging EMAs for instantaneous Z-Score (Statistical) analysis.
    2.  Alpha: Detects 'Volatility Expansion' - entering only when price moves > 2.0 StdDevs from the mean with high velocity.
    3.  Risk Control: 'Oxygen Mask' protocol. Tighter stops (-3%) to preserve the $536 capital, with aggressive trailing stops to lock wins.
    4.  Hive Mind: Fully integrates penalty signals to blacklist toxic assets.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Gen 6: Phoenix Z-Score)")
        
        # === Configuration ===
        self.lookback_window = 20       # Short window for rapid reaction
        self.z_score_threshold = 2.0    # Statistical breakout trigger
        self.min_velocity = 0.5         # Minimum % change to confirm momentum
        
        # === Risk Management (Survival Mode) ===
        self.max_positions = 3          # Limit exposure
        self.stop_loss_pct = 0.03       # Tight 3% hard stop
        self.trailing_start = 0.05      # Start trailing after 5% gain
        self.trailing_step = 0.02       # Trail by 2%
        self.trade_size_usd = 100.0     # Fixed trade size (approx 20% of current equity)
        
        # === State ===
        self.price_history = defaultdict(lambda: deque(maxlen=self.lookback_window))
        self.positions = {}             # {symbol: {'entry_price': float, 'highest_price': float}}
        self.banned_tags = set()
        self.last_prices = {}

    def on_hive_signal(self, signal: dict):
        """Absorb Hive Mind wisdom to avoid toxic assets"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🛡️ Phoenix Shield: Banning {penalize}")
            self.banned_tags.update(penalize)

    def get_z_score(self, symbol, current_price):
        """Calculate statistical anomaly score"""
        history = self.price_history[symbol]
        if len(history) < self.lookback_window:
            return 0.0
        
        mean_price = statistics.mean(history)
        std_dev = statistics.stdev(history)
        
        if std_dev == 0:
            return 0.0
            
        return (current_price - mean_price) / std_dev

    def on_price_update(self, prices: dict):
        """
        Core Logic: Volatility Expansion Breakout
        """
        decision = None
        
        # 1. Update History & Calculate Metrics
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Update history
            self.price_history[symbol].append(current_price)
            
            # Calculate Velocity (% change since last tick)
            last_price = self.last_prices.get(symbol, current_price)
            velocity = ((current_price - last_price) / last_price) * 100 if last_price > 0 else 0
            self.last_prices[symbol] = current_price

            # Check Banned Tags (if data contains tags, usually in metadata, assuming symbol check here)
            if symbol in self.banned_tags:
                continue

            # === EXIT LOGIC (Risk Management First) ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos['entry_price']
                
                # Update highest price seen for trailing stop
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
                
                # Calculate PnL %
                pnl_pct = (current_price - entry_price) / entry_price
                
                # A. Hard Stop Loss
                if pnl_pct < -self.stop_loss_pct:
                    print(f"🛑 STOP LOSS: {symbol} at {pnl_pct:.2%}")
                    del self.positions[symbol]
                    return {"symbol": symbol, "action": "sell", "amount": "all"}
                
                # B. Trailing Stop Profit
                # If we hit trailing start, check if we fell back by trailing step
                highest_pct = (pos['highest_price'] - entry_price) / entry_price
                if highest_pct >= self.trailing_start:
                    drawdown_from_high = (pos['highest_price'] - current_price) / pos['highest_price']
                    if drawdown_from_high >= self.trailing_step:
                        print(f"💰 TAKE PROFIT (Trailing): {symbol} at {pnl_pct:.2%}")
                        del self.positions[symbol]
                        return {"symbol": symbol, "action": "sell", "amount": "all"}
                
                continue # Skip entry logic if we hold position

            # === ENTRY LOGIC (Phoenix Breakout) ===
            # Only look for entries if we have slots open
            if len(self.positions) < self.max_positions:
                z_score = self.get_z_score(symbol, current_price)
                
                # Mutation: Buy if price is statistically anomalous (high Z-score) AND moving fast (Velocity)
                # This catches the "Pump" early
                if z_score > self.z_score_threshold and velocity > self.min_velocity:
                    print(f"🚀 BREAKOUT: {symbol} | Z: {z_score:.2f} | Vel: {velocity:.2f}%")
                    
                    # Record Position
                    self.positions[symbol] = {
                        'entry_price': current_price,
                        'highest_price': current_price
                    }
                    
                    # Return Buy Decision
                    # Note: Darwin SDK usually expects 'amount' in USD or token quantity. 
                    # Using USD based on survival config.
                    return {"symbol": symbol, "action": "buy", "amount": self.trade_size_usd}

        return decision