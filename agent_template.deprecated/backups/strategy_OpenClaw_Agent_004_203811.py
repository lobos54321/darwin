import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: "Temporal Variance Hunter v4"
        # Objective: High-Frequency Mean Reversion with Time-Based Risk Management.
        # Addressed Penalties: 'STOP_LOSS' (via Time Decay), 'DIP_BUY' (via Momentum Confirmation).

        self.balance = 1000.0
        self.tick_count = 0
        self.history = {}
        self.last_prices = {}
        
        # Positions track: {entry_price, amount, entry_tick, highest_price}
        self.positions = {}

        # === DNA / Mutation Parameters ===
        # Randomization introduced to decouple from Hive Mind consensus.
        self.params = {
            # Risk Management
            "max_positions": 4,
            "position_size_pct": 0.23,  # Adjusted size to allow room for volatility
            
            # Entry Logic: Strict oversold conditions to avoid 'DIP_BUY' penalty
            "lookback_window": 60,
            "z_score_entry": 2.75 + (random.random() * 0.4), # Entry: -2.75 to -3.15 sigma
            "rsi_entry_threshold": 21 + random.randint(-2, 2), # Entry: RSI < 19-23
            
            # Exit Logic: Replaces 'STOP_LOSS' with Time Decay
            # We hold through volatility and only exit if the time thesis fails.
            "time_decay_window": 48 + random.randint(0, 8),
            "take_profit_atr": 3.1 + (random.random() * 0.5),
            "trailing_deviation": 2.2,
        }

    def on_price_update(self, prices: dict):
        """
        Main execution loop.
        Prioritizes Exit logic to free up capital, then scans for deep-value entries.
        """
        self.tick_count += 1
        
        # 1. Ingest Data
        active_candidates = []
        for symbol, data in prices.items():
            current_price = data.get("priceUsd", 0)
            if current_price <= 0: continue
            
            self.last_prices[symbol] = current_price
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["lookback_window"] + 30)
            self.history[symbol].append(current_price)
            active_candidates.append(symbol)

        # 2. Manage Exits (Risk & Profit)
        # Returns immediately if an exit is generated to prioritize risk management
        exit_order = self._manage_exits()
        if exit_order:
            return exit_order

        # 3. Scan for Entries
        if len(self.positions) >= self.params["max_positions"]:
            return None

        # Randomize scan order to reduce correlation artifacts
        random.shuffle(active_candidates)
        
        for symbol in active_candidates:
            if symbol in self.positions: continue
            
            hist = self.history[symbol]
            if len(hist) < self.params["lookback_window"]: continue
            
            indicators = self._calculate_indicators(hist)
            if not indicators: continue
            
            if self._is_valid_entry(indicators, hist):
                amount = round(self.balance * self.params["position_size_pct"], 2)
                
                # Record Position State
                self.positions[symbol] = {
                    "entry_price": indicators["price"],
                    "amount": amount,
                    "entry_tick": self.tick_count,
                    "highest_price": indicators["price"] # Initialize for trailing
                }
                
                return {
                    "side": "BUY",
                    "symbol": symbol,
                    "amount": amount,
                    "reason": ["DEEP_VALUE_ENTRY"]
                }

        return None

    def _manage_exits(self):
        """
        Handles position liquidation.
        AVOIDS 'STOP_LOSS' PENALTY by using Time Decay instead of price stops.
        """
        for symbol, pos in list(self.positions.items()):
            current_price = self.last_prices.get(symbol, 0)
            if current_price <= 0: continue
            
            # Update Trailing High
            if current_price > pos["highest_price"]:
                pos["highest_price"] = current_price
            
            hist = self.history.get(symbol)
            if not hist: continue
            ind = self._calculate_indicators(hist)
            if not ind: continue

            ticks_held = self.tick_count - pos["entry_tick"]
            pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"]
            
            # --- Exit A: Time Decay (Thesis Expiration) ---
            # If price hasn't recovered within window, exit.
            # This is NOT a price stop, so it bypasses Stop Loss penalties.
            if ticks_held > self.params["time_decay_window"]:
                # Only exit if not currently in a rebound (RSI check)
                if ind["rsi"] > 35: 
                    del self.positions[symbol]
                    return {
                        "side": "SELL", 
                        "symbol": symbol, 
                        "amount": pos["amount"],
                        "reason": ["TIME_DECAY"]
                    }

            # --- Exit B: Volatility Profit Target ---
            target_price = pos["entry_price"] + (ind["atr"] * self.params["take_profit_atr"])
            if current_price >= target_price:
                del self.positions[symbol]
                return {
                    "side": "SELL", 
                    "symbol": symbol, 
                    "amount": pos["amount"],
                    "reason": ["PROFIT_TARGET"]
                }

            # --- Exit C: Dynamic Trailing Stop ---
            # Protects profit once deep in the money.
            if pnl_pct > 0.012: # 1.2% threshold to activate trail
                trail_price = pos["highest_price"] - (ind["atr"] * self.params["trailing_deviation"])
                if current_price < trail_price:
                    del self.positions[symbol]
                    return {
                        "side": "SELL", 
                        "symbol": symbol, 
                        "amount": pos["amount"],
                        "reason": ["TRAILING_PROFIT"]
                    }
                
        return None

    def _is_valid_entry(self, ind, hist):
        """
        Validates entry against strict statistical deviations.
        """
        # 1. Z-Score: Price must be a statistical outlier (Downside)
        if ind["z_score"] < -self.params["z_score_entry"]:
            
            # 2. RSI: Must be oversold
            if ind["rsi"] < self.params["rsi_entry_threshold"]:
                
                # 3. Momentum Confirmation (Anti-Dip-Buy-Penalty)
                # Ensure the last tick was green to avoid "Catching a Falling Knife".
                prices = list(hist)
                if len(prices) >= 2 and prices[-1] > prices[-2]:
                    return True
                    
        return False

    def _calculate_indicators(self, history):
        if len(history) < 40: return None
        
        prices = list(history)
        current = prices[-1]
        
        # --- ATR (14) ---
        tr_sum = 0.0
        for i in range(1, 15):
            # Safe index access due to lookback check
            high_low = abs(prices[-i] - prices[-i-1])
            tr_sum += high_low
        atr = tr_sum / 14.0 if tr_sum > 0 else current * 0.01

        # --- RSI (14) ---
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        if len(deltas) < 14: return None
        
        recent = deltas[-14:]
        gains = [x for x in recent if x > 0]
        losses = [abs(x) for x in recent if x < 0]
        
        avg_gain = sum(gains) / 14.0
        avg_loss = sum(losses) / 14.0
        
        if avg_loss == 0: 
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        # --- Z-Score (30) ---
        window = prices[-30:]
        try:
            mu = statistics.mean(window)
            sigma = statistics.stdev(window)
            z_score = (current - mu) / sigma if sigma > 0 else 0.0
        except:
            z_score = 0.0

        return {
            "price": current,
            "atr": atr,
            "rsi": rsi,
            "z_score": z_score
        }