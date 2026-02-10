import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital Configuration ===
        self.balance = 1000.0             # Base capital for sizing
        self.allocation_pct = 0.18        # 18% per trade (conservative sizing)
        self.max_positions = 5            # Max concurrent trades
        
        # === Risk Management ===
        self.hard_stop_pct = 0.06         # 6% Structural Stop (Not trailing)
        self.max_hold_ticks = 45          # Force exit to recycle capital
        self.min_liquidity = 600000.0     # Avoid thin books
        
        # === Mean Reversion Logic ===
        self.lookback = 24                # Window for Moving Average
        self.entry_z_score = 2.6          # Entry Threshold (Strict >2.6 SD deviation)
        self.exit_z_threshold = 0.0       # Exit when price returns to Mean
        
        # === State ===
        self.positions = {}               # Track active trades
        self.price_history = {}           # Store recent price data
        
    def _calculate_stats(self, history):
        """Calculates Simple Moving Average and Standard Deviation."""
        if len(history) < self.lookback:
            return None, None
            
        # Extract window
        window = list(history)[-self.lookback:]
        n = len(window)
        
        # Mean
        sma = sum(window) / n
        
        # Sample Standard Deviation
        variance = sum((x - sma) ** 2 for x in window) / (n - 1)
        std_dev = math.sqrt(variance)
        
        return sma, std_dev

    def on_price_update(self, prices):
        """
        Executed on every price tick.
        Prioritizes Exits, then Scans for Entries.
        """
        
        # --- 1. EXIT LOGIC ---
        # Iterate copy of keys to allow deletion during iteration
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            try:
                current_price = float(prices[symbol]["priceUsd"])
                pos = self.positions[symbol]
                
                # Update tick counter for time-based exit
                pos["ticks"] += 1
                
                # Update History (Essential for dynamic exit target)
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.lookback + 5)
                self.price_history[symbol].append(current_price)
                
                # Calculate Dynamic Mean
                sma, _ = self._calculate_stats(self.price_history[symbol])
                
                exit_reason = None
                
                # A. Structural Hard Stop (Risk Control)
                # Using fixed price determined at entry (No Trailing)
                if current_price <= pos["stop_loss"]:
                    exit_reason = "STRUCTURAL_STOP"
                
                # B. Time Expiry (Opportunity Cost)
                elif pos["ticks"] >= self.max_hold_ticks:
                    exit_reason = "TIME_DECAY"
                    
                # C. Mean Reversion (Profit Taking)
                # Dynamic exit: Price has reverted to the mean (SMA)
                elif sma is not None and current_price >= sma:
                    exit_reason = "MEAN_REVERTED"
                
                if exit_reason:
                    amount = pos["amount"]
                    del self.positions[symbol]
                    return {
                        "side": "SELL",
                        "symbol": symbol,
                        "amount": amount,
                        "reason": [exit_reason]
                    }
                    
            except (ValueError, TypeError, KeyError):
                continue

        # --- 2. ENTRY LOGIC ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
                
            try:
                price = float(data["priceUsd"])
                liquidity = float(data.get("liquidity", 0))
                
                # 1. Filter: Liquidity
                if liquidity < self.min_liquidity:
                    continue
                
                # 2. History Maintenance
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.lookback + 5)
                self.price_history[symbol].append(price)
                
                if len(self.price_history[symbol]) < self.lookback:
                    continue
                    
                # 3. Indicator Calculation
                sma, std_dev = self._calculate_stats(self.price_history[symbol])
                
                if sma is None or std_dev == 0:
                    continue
                
                # 4. Signal Generation: Volatility Adjusted Dip
                # We want price significantly BELOW the mean (Negative Z-Score)
                deviation = price - sma
                
                # Filter out positive deviations (Breakouts)
                if deviation >= 0:
                    continue
                    
                z_score = deviation / std_dev
                
                # Check Threshold (Strict Entry)
                if z_score < -self.entry_z_score:
                    # Score is the intensity of the dip
                    candidates.append({
                        "symbol": symbol,
                        "price": price,
                        "z_score": z_score
                    })
                    
            except (ValueError, TypeError, KeyError):
                continue
                
        # --- 3. EXECUTION ---
        if candidates:
            # Select the most extreme statistical anomaly (lowest Z-score)
            best_opp = min(candidates, key=lambda x: x["z_score"])
            
            entry_price = best_opp["price"]
            symbol = best_opp["symbol"]
            
            # Position Sizing
            trade_value = self.balance * self.allocation_pct
            amount = trade_value / entry_price
            
            # Register Position
            self.positions[symbol] = {
                "amount": amount,
                "entry_price": entry_price,
                "ticks": 0,
                # Fixed Stop Level (Calculated once)
                "stop_loss": entry_price * (1.0 - self.hard_stop_pct)
            }
            
            return {
                "side": "BUY",
                "symbol": symbol,
                "amount": amount,
                "reason": ["VOL_IMBALANCE"]
            }
            
        return None