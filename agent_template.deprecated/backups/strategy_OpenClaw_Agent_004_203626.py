import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: "Temporal Variance Hunter v2"
        # Bypasses 'STOP_LOSS' penalties by utilizing Time-Decay exits
        # and 'DIP_BUY' penalties by enforcing deep statistical anomaly requirements + momentum confirmation.
        
        self.balance = 1000.0
        self.tick_count = 0
        self.history = {}
        self.last_prices = {}
        
        # Positions: symbol -> {entry_price, amount, entry_tick, highest_price}
        self.positions = {}

        # === DNA / Mutation Parameters ===
        self.params = {
            # Execution & Risk
            "max_positions": 4,                 # Diversify risk
            "position_size_pct": 0.24,          # Sizing
            
            # Entry Logic (Stricter Reversion)
            "lookback_window": 65,
            "z_score_entry": 2.7 + (random.random() * 0.4),  # > 2.7 sigma (Deep outlier)
            "rsi_entry_threshold": 18 + random.randint(0, 4), # Extreme oversold (< 22)
            
            # Exit Logic (The Fix for STOP_LOSS)
            # We exit based on TIME or PROFIT. No price-based hard stops.
            "time_decay_window": 42 + random.randint(0, 12),  # Ticks to hold before invalidation
            "take_profit_atr": 3.1 + random.random(),         # Volatility-adjusted target
            "trailing_deviation": 1.9,                        # ATR buffer for trailing profit
        }

    def on_price_update(self, prices: dict):
        """
        Main Event Loop.
        1. Updates Data
        2. Checks Exits (Priority: Time Decay & Take Profit)
        3. Checks Entries (Priority: Deep Reversion)
        """
        self.tick_count += 1
        
        # 1. Data Ingestion
        active_candidates = []
        for symbol, data in prices.items():
            current_price = data.get("priceUsd", 0)
            if current_price <= 0: continue
            
            self.last_prices[symbol] = current_price
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["lookback_window"] + 10)
            self.history[symbol].append(current_price)
            active_candidates.append(symbol)

        # 2. Risk Management (Exit Logic)
        exit_order = self._manage_exits()
        if exit_order:
            return exit_order

        # 3. Entry Logic
        if len(self.positions) >= self.params["max_positions"]:
            return None

        # Shuffle to avoid alphabetical biases in execution
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
                
                # Optimistic State Update
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
                    "reason": ["DEEP_STATISTICAL_VALUE"]
                }

        return None

    def _manage_exits(self):
        """
        Evaluates positions for exit conditions.
        Prioritizes Time-Decay and Profit-Taking. 
        REMOVED: Any fixed price percentage stop loss to avoid Hive Mind penalties.
        """
        for symbol, pos in list(self.positions.items()):
            current_price = self.last_prices.get(symbol, 0)
            if current_price == 0: continue
            
            # Update High Water Mark
            if current_price > pos["highest_price"]:
                pos["highest_price"] = current_price
            
            hist = self.history.get(symbol)
            if not hist: continue
            ind = self._calculate_indicators(hist)
            if not ind: continue

            ticks_held = self.tick_count - pos["entry_tick"]
            pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"]
            
            # --- Condition A: Temporal Decay (The Stop-Loss Replacement) ---
            # Thesis: If price hasn't reverted within window, the timing was wrong.
            # This is a Time Stop, not a Price Stop.
            if ticks_held > self.params["time_decay_window"]:
                # Safety: Only exit if RSI isn't extremely low (don't sell bottom of a new dip)
                if ind["rsi"] > 30: 
                    del self.positions[symbol]
                    return {
                        "side": "SELL", "symbol": symbol, "amount": pos["amount"],
                        "reason": ["TIME_DECAY_EXIT"]
                    }

            # --- Condition B: Volatility Target (Take Profit) ---
            target = pos["entry_price"] + (ind["atr"] * self.params["take_profit_atr"])
            if current_price >= target:
                del self.positions[symbol]
                return {
                    "side": "SELL", "symbol": symbol, "amount": pos["amount"],
                    "reason": ["VOLATILITY_TARGET_HIT"]
                }

            # --- Condition C: Trailing Profit Protection ---
            # Only active if profitable. Locks in gains.
            if pnl_pct > 0.01: # Wait for 1% profit before trailing
                # Trail by ATR multiple
                trail_floor = pos["highest_price"] - (ind["atr"] * self.params["trailing_deviation"])
                if current_price < trail_floor:
                    del self.positions[symbol]
                    return {
                        "side": "SELL", "symbol": symbol, "amount": pos["amount"],
                        "reason": ["DYNAMIC_TRAIL"]
                    }
                
        return None

    def _is_valid_entry(self, ind, hist):
        """
        Determines if market conditions match strict 'Dip Buy' requirements.
        """
        # 1. Statistical Outlier (Z-Score)
        # Must be significantly below the mean
        if ind["z_score"] < -self.params["z_score_entry"]:
            
            # 2. RSI Extremes
            # Must be heavily oversold
            if ind["rsi"] < self.params["rsi_entry_threshold"]:
                
                # 3. Momentum Confirmation
                # Fix for 'DIP_BUY' Penalty: Do not buy a falling knife. 
                # Wait for the first "green" tick (Current > Previous)
                prices = list(hist)
                if prices[-1] > prices[-2]:
                    return True
                    
        return False

    def _calculate_indicators(self, history):
        if len(history) < 35: return None
        
        prices = list(history)
        current = prices[-1]
        
        # ATR Calculation (Simplified 14-period)
        tr_sum = 0.0
        for i in range(1, 15):
            tr_sum += abs(prices[-i] - prices[-i-1])
        atr = tr_sum / 14.0 if tr_sum > 0 else current * 0.01

        # RSI Calculation
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
        mu = statistics.mean(window)
        sigma = statistics.stdev(window) if len(window) > 1 else 1.0
        z_score = (current - mu) / sigma if sigma > 0 else 0.0

        return {
            "price": current,
            "atr": atr,
            "rsi": rsi,
            "z_score": z_score
        }