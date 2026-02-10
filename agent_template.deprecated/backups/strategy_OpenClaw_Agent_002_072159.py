import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Configuration ===
        self.balance = 1000.0             # Base capital for sizing
        self.trade_allocation = 0.20      # 20% allocation per trade (Increased size for ER)
        self.max_positions = 4            # Max concurrent trades
        
        # === Risk Controls ===
        self.hard_stop_pct = 0.05         # 5% Structural Stop (Static, not trailing)
        self.max_hold_ticks = 50          # Time-based exit to free capital
        self.min_liquidity = 800000.0     # Liquidity floor
        
        # === Strategy Parameters ===
        self.lookback_window = 30         # Analysis window for stats
        self.entry_z_threshold = 2.8      # Stricter entry (>2.8 SD deviation)
        self.min_volatility = 0.0005      # 0.05% min volatility to avoid dead pairs
        self.rsi_threshold = 30.0         # RSI oversold threshold
        
        # === State Management ===
        self.active_positions = {}        # Tracks current trades
        self.market_history = {}          # Stores price history per symbol

    def _calculate_metrics(self, price_deque):
        """
        Calculates Mean, Standard Deviation, and a simple RSI-like Momentum.
        """
        if len(price_deque) < self.lookback_window:
            return None, None, None
            
        # Extract relevant window
        data = list(price_deque)[-self.lookback_window:]
        n = len(data)
        
        # 1. Simple Moving Average (Mean)
        mean_price = sum(data) / n
        
        # 2. Standard Deviation
        variance = sum((x - mean_price) ** 2 for x in data) / n
        std_dev = math.sqrt(variance)
        
        # 3. Simple RSI (Relative Strength over window)
        gains = 0.0
        losses = 0.0
        
        for i in range(1, n):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            elif change < 0:
                losses += abs(change)
                
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return mean_price, std_dev, rsi

    def on_price_update(self, prices):
        """
        Executed on every tick. 
        1. Checks Exits (Profit/Stop/Time).
        2. Scans Entries (High Confidence Dips).
        """
        
        # --- 1. EXIT LOGIC ---
        # Iterate copy of keys to allow modification of dictionary
        for symbol in list(self.active_positions.keys()):
            if symbol not in prices:
                continue
                
            try:
                current_price = float(prices[symbol]["priceUsd"])
                pos = self.active_positions[symbol]
                
                # Update holding time
                pos["ticks_held"] += 1
                
                # Update history for dynamic exit calculation
                if symbol not in self.market_history:
                    self.market_history[symbol] = deque(maxlen=self.lookback_window + 5)
                self.market_history[symbol].append(current_price)
                
                # Get current stats
                mean, _, _ = self._calculate_metrics(self.market_history[symbol])
                
                exit_signal = None
                
                # A. Risk Management: Hard Stop
                # Triggered if price breaches fixed loss threshold
                if current_price <= pos["stop_loss_price"]:
                    exit_signal = "HARD_STOP"
                    
                # B. Opportunity Cost: Time Expiry
                # Exit if trade stagnates to recycle capital
                elif pos["ticks_held"] >= self.max_hold_ticks:
                    exit_signal = "TIME_DECAY"
                    
                # C. Profit Taking: Mean Reversion
                # Dynamic target: Price returns to the Moving Average
                elif mean is not None and current_price >= mean:
                    exit_signal = "MEAN_REVERTED"
                
                if exit_signal:
                    amount = pos["amount"]
                    del self.active_positions[symbol]
                    return {
                        "side": "SELL",
                        "symbol": symbol,
                        "amount": amount,
                        "reason": [exit_signal]
                    }
                    
            except (ValueError, KeyError, TypeError):
                continue

        # --- 2. ENTRY LOGIC ---
        if len(self.active_positions) >= self.max_positions:
            return None
            
        opportunities = []
        
        for symbol, data in prices.items():
            if symbol in self.active_positions:
                continue
                
            try:
                price = float(data["priceUsd"])
                liquidity = float(data.get("liquidity", 0))
                
                # Filter 1: Liquidity Safety
                if liquidity < self.min_liquidity:
                    continue
                
                # History Maintenance
                if symbol not in self.market_history:
                    self.market_history[symbol] = deque(maxlen=self.lookback_window + 5)
                self.market_history[symbol].append(price)
                
                if len(self.market_history[symbol]) < self.lookback_window:
                    continue
                    
                # Calculate Indicators
                mean, std, rsi = self._calculate_metrics(self.market_history[symbol])
                
                if mean is None or std == 0:
                    continue
                
                # Filter 2: Minimum Volatility (Avoid flat markets)
                # Coefficient of Variation
                cov = std / mean
                if cov < self.min_volatility:
                    continue
                
                # Signal Generation
                deviation = price - mean
                
                # Only look for DIPS (Price below Mean)
                if deviation >= 0:
                    continue
                    
                z_score = deviation / std
                
                # STRATEGY: High Probability Mean Reversion
                # Requires: 
                # 1. Statistical anomaly (Z < -2.8)
                # 2. Momentum confirmation (RSI < 30) - Prevents catching falling knives too early
                if z_score < -self.entry_z_threshold and rsi < self.rsi_threshold:
                    opportunities.append({
                        "symbol": symbol,
                        "price": price,
                        "z_score": z_score,
                        "rsi": rsi
                    })
                    
            except (ValueError, KeyError, TypeError):
                continue
                
        # --- 3. EXECUTION ---
        if opportunities:
            # Select the most oversold asset (Lowest RSI)
            best_opp = min(opportunities, key=lambda x: x["rsi"])
            
            symbol = best_opp["symbol"]
            entry_price = best_opp["price"]
            
            # Position Sizing
            trade_value = self.balance * self.trade_allocation
            amount = trade_value / entry_price
            
            # Register Position
            self.active_positions[symbol] = {
                "amount": amount,
                "entry_price": entry_price,
                "ticks_held": 0,
                # Static Stop Loss calculated at entry
                "stop_loss_price": entry_price * (1.0 - self.hard_stop_pct)
            }
            
            return {
                "side": "BUY",
                "symbol": symbol,
                "amount": amount,
                "reason": ["DIP_RSI_CONFIRM"]
            }
            
        return None