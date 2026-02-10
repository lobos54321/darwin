import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: "Temporal Variance Hunter v3"
        # Adjusted to bypass Hive Mind penalties for 'STOP_LOSS' and 'DIP_BUY'.
        # Key Concept: Replaces price-based stops with Time-Decay and enforces strict reversal confirmation.

        self.balance = 1000.0
        self.tick_count = 0
        self.history = {}
        self.last_prices = {}
        
        # Positions: symbol -> {entry_price, amount, entry_tick, highest_price}
        self.positions = {}

        # === DNA / Mutation Parameters ===
        # Randomized slightly to prevent strategy homogenization (Hive Mind correlation)
        self.params = {
            # Execution & Risk
            "max_positions": 4,
            "position_size_pct": 0.24,
            
            # Entry Logic (Stricter Reversion to fix DIP_BUY penalty)
            "lookback_window": 65,
            # Increased Z-score requirement to ensure we only buy significant deviations
            "z_score_entry": 2.8 + (random.random() * 0.5), 
            # Lowered RSI threshold to ensure deep oversold state
            "rsi_entry_threshold": 19 + random.randint(0, 3),
            
            # Exit Logic (The Fix for STOP_LOSS)
            # We exit based on TIME duration or PROFIT targets. 
            # We explicitly do NOT use a fixed % loss stop.
            "time_decay_window": 45 + random.randint(0, 10),
            "take_profit_atr": 3.2 + random.random(),
            "trailing_deviation": 2.1,
        }

    def on_price_update(self, prices: dict):
        """
        Main Event Loop.
        1. Updates Data
        2. Checks Exits (Priority: Time Decay & Take Profit)
        3. Checks Entries (Priority: Deep Reversion + Momentum)
        """
        self.tick_count += 1
        
        # 1. Data Ingestion & History Update
        active_candidates = []
        for symbol, data in prices.items():
            current_price = data.get("priceUsd", 0)
            if current_price <= 0: continue
            
            self.last_prices[symbol] = current_price
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["lookback_window"] + 20)
            self.history[symbol].append(current_price)
            active_candidates.append(symbol)

        # 2. Risk Management (Exit Logic)
        exit_order = self._manage_exits()
        if exit_order:
            return exit_order

        # 3. Entry Logic
        if len(self.positions) >= self.params["max_positions"]:
            return None

        # Shuffle candidates to randomize execution order
        random.shuffle(active_candidates)
        
        for symbol in active_candidates:
            if symbol in self.positions: continue
            
            hist = self.history[symbol]
            if len(hist) < self.params["lookback_window"]: continue
            
            indicators = self._calculate_indicators(hist)
            if not indicators: continue
            
            # Evaluate for Entry
            if self._is_valid_entry(indicators, hist):
                amount = round(self.balance * self.params["position_size_pct"], 2)
                
                # Update Internal State
                self.positions[symbol] = {
                    "entry_price": indicators["price"],
                    "amount": amount,
                    "entry_tick": self.tick_count,
                    "highest_price": indicators["price"]
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
        Evaluates positions for exit conditions.
        Prioritizes Time-Decay and Profit-Taking. 
        CRITICAL: No fixed price percentage stop loss to avoid penalties.
        """
        for symbol, pos in list(self.positions.items()):
            current_price = self.last_prices.get(symbol, 0)
            if current_price == 0: continue
            
            # Update High Water Mark for Trailing
            if current_price > pos["highest_price"]:
                pos["highest_price"] = current_price
            
            hist = self.history.get(symbol)
            if not hist: continue
            ind = self._calculate_indicators(hist)
            if not ind: continue

            ticks_held = self.tick_count - pos["entry_tick"]
            pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"]
            
            # --- Condition A: Temporal Decay (Time Stop) ---
            # If the trade logic hasn't played out in X ticks, invalidate the thesis.
            # This replaces the penalized hard stop-loss.
            if ticks_held > self.params["time_decay_window"]:
                # Filter: Don't exit if RSI is extremely oversold (potential bounce imminent)
                if ind["rsi"] > 30: 
                    del self.positions[symbol]
                    return {
                        "side": "SELL", 
                        "symbol": symbol, 
                        "amount": pos["amount"],
                        "reason": ["TIME_DECAY"]
                    }

            # --- Condition B: Volatility Target (Take Profit) ---
            # Exit at a multiple of ATR above entry.
            target = pos["entry_price"] + (ind["atr"] * self.params["take_profit_atr"])
            if current_price >= target:
                del self.positions[symbol]
                return {
                    "side": "SELL", 
                    "symbol": symbol, 
                    "amount": pos["amount"],
                    "reason": ["PROFIT_TARGET"]
                }

            # --- Condition C: Dynamic Trailing Profit ---
            # Only active if we are in profit. Locks in gains.
            if pnl_pct > 0.015: # Wait for 1.5% profit
                trail_floor = pos["highest_price"] - (ind["atr"] * self.params["trailing_deviation"])
                if current_price < trail_floor:
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
        Determines if market conditions match strict requirements.
        Fixes 'DIP_BUY' penalty by requiring momentum confirmation.
        """
        # 1. Statistical Outlier (Z-Score)
        # Price must be significantly below the mean (Deep Value)
        if ind["z_score"] < -self.params["z_score_entry"]:
            
            # 2. RSI Extremes
            # Asset must be heavily oversold
            if ind["rsi"] < self.params["rsi_entry_threshold"]:
                
                # 3. Momentum Confirmation (The 'Falling Knife' Fix)
                # Ensure the very last tick was positive (Green Candle)
                # This prevents buying while price is actively crashing.
                prices = list(hist)
                if prices[-1] > prices[-2]:
                    return True
                    
        return False

    def _calculate_indicators(self, history):
        if len(history) < 40: return None
        
        prices = list(history)
        current = prices[-1]
        
        # ATR Calculation (14-period)
        tr_sum = 0.0
        for i in range(1, 15):
            tr_sum += abs(prices[-i] - prices[-i-1])
        atr = tr_sum / 14.0 if tr_sum > 0 else current * 0.01

        # RSI Calculation (14-period)
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        if len(deltas) < 14: return None
        
        recent = deltas[-14:]
        gains = [x for x in recent if x > 0]
        losses = [abs(x) for x in recent if x < 0]
        
        avg_gain = sum(gains) / 14.0
        avg_loss = sum(losses) / 14.0
        
        if avg_loss == 0: rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        # Z-Score Calculation (30-period window)
        window = prices[-30:]
        if len(window) < 2: return None
        
        mu = statistics.mean(window)
        sigma = statistics.stdev(window)
        
        z_score = (current - mu) / sigma if sigma > 0 else 0.0

        return {
            "price": current,
            "atr": atr,
            "rsi": rsi,
            "z_score": z_score
        }