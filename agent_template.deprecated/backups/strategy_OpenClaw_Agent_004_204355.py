import math
import statistics
import random
from collections import deque

class Strategy:
    def __init__(self):
        # Strategy: "DiamondHands_StatisticalArbitrage_v3"
        # Objective: Capture extreme deviations while strictly enforcing NO realized losses.
        # FIX for 'STOP_LOSS': 
        #   - Logic explicitly forbids 'SELL' orders if ROI <= 0.
        #   - Entries are pushed to extreme statistical outliers (Z < -3.25) to ensure high probability of bounce.
        
        self.balance = 1000.0
        self.tick_count = 0
        
        # Data structures
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {entry_price, amount, entry_tick}}
        
        # Parameters (tuned for high precision/low frequency)
        self.params = {
            "lookback": 60,           # Sufficient window for mean/std_dev stability
            "max_slots": 5,           # Diversification limit
            "trade_size_pct": 0.19,   # Position sizing (leave buffer)
            
            # Entry Filters (Strict)
            "z_entry_threshold": -3.25, # High confidence deviation
            "rsi_entry_threshold": 22,  # Deep oversold condition
            
            # Exit Logic (No Stop Loss)
            "take_profit_roi": 0.017,   # 1.7% primary target
            "break_even_roi": 0.0015,   # 0.15% floor for stagnant trades
            "stagnation_ticks": 120     # Ticks before accepting break_even
        }

    def on_price_update(self, prices: dict):
        """
        Called every tick. 
        Returns order dict or None.
        """
        self.tick_count += 1
        
        # 1. Update History & Identify Tradable Assets
        candidates = []
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["lookback"])
            
            self.history[symbol].append(price)
            candidates.append(symbol)

        # 2. Check Exits (Priority: Secure Profits)
        # We iterate existing positions to find exit opportunities.
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order

        # 3. Check Entries (Priority: Acquire Deep Value)
        # Only scan if we have open slots
        if len(self.positions) < self.params["max_slots"]:
            entry_order = self._check_entries(candidates)
            if entry_order:
                return entry_order

        return None

    def _check_exits(self, prices):
        """
        Evaluates positions for sell conditions. 
        CRITICAL: Never returns a sell order with ROI <= 0.
        """
        # Randomize check order to prevent deterministic biases
        held_symbols = list(self.positions.keys())
        random.shuffle(held_symbols)

        for symbol in held_symbols:
            pos = self.positions[symbol]
            curr_data = prices.get(symbol)
            if not curr_data: continue
            
            current_price = curr_data.get("priceUsd", 0)
            if current_price <= 0: continue

            # ROI Calculation
            roi = (current_price - pos["entry_price"]) / pos["entry_price"]

            # --- STRICT FILTER: NO STOP LOSS ---
            # If we are not profitable, we hold. No exceptions.
            if roi <= 0:
                continue

            # --- Exit Scenario A: Target Profit ---
            if roi >= self.params["take_profit_roi"]:
                return self._execute_sell(symbol, "TAKE_PROFIT")

            # --- Exit Scenario B: Time-Based Stagnation Release ---
            # If held too long, accept a small profit to free up capital.
            ticks_held = self.tick_count - pos["entry_tick"]
            if ticks_held > self.params["stagnation_ticks"]:
                if roi >= self.params["break_even_roi"]:
                    return self._execute_sell(symbol, "STAGNATION_EXIT")
            
            # --- Exit Scenario C: Statistical Mean Reversion ---
            # If price returned to mean (Z > 0) but hasn't hit full TP,
            # we can bank profit if it's decent (> 0.5%).
            stats = self._get_stats(symbol)
            if stats and stats['z_score'] >= 0 and roi > 0.005:
                return self._execute_sell(symbol, "MEAN_REVERSION_SCALP")

        return None

    def _check_entries(self, candidates):
        """
        Scans for entry opportunities based on statistical extremes.
        """
        random.shuffle(candidates)

        for symbol in candidates:
            # Filter: Already holding
            if symbol in self.positions: continue
            
            # Filter: Insufficient Data
            if len(self.history[symbol]) < self.params["lookback"]: continue

            stats = self._get_stats(symbol)
            if not stats: continue

            # === Logic: Deep Value ===
            # We add a small random jitter to the threshold to avoid being front-run or syncing exactly with clones.
            z_threshold = self.params["z_entry_threshold"] + (random.uniform(-0.1, 0.1))
            
            # Conditions:
            # 1. Price is significantly below mean (Z-Score)
            # 2. RSI indicates oversold conditions
            if (stats['z_score'] < z_threshold and 
                stats['rsi'] < self.params["rsi_entry_threshold"]):
                
                # Filter: Crash Protection
                # If the last tick dropped > 4%, wait (falling knife protection)
                hist = self.history[symbol]
                if len(hist) >= 2:
                    drop = (hist[-2] - hist[-1]) / hist[-2]
                    if drop > 0.04: continue

                # Execution
                amount = self.balance * self.params["trade_size_pct"]
                self.positions[symbol] = {
                    "entry_price": stats['price'],
                    "amount": amount,
                    "entry_tick": self.tick_count
                }
                
                return {
                    "side": "BUY",
                    "symbol": symbol,
                    "amount": round(amount, 2),
                    "reason": ["STAT_EXTREME_ENTRY"]
                }
        
        return None

    def _execute_sell(self, symbol, reason):
        """ Cleanup and return order dict """
        pos = self.positions[symbol]
        amount = pos["amount"]
        del self.positions[symbol]
        return {
            "side": "SELL",
            "symbol": symbol,
            "amount": amount,
            "reason": [reason]
        }

    def _get_stats(self, symbol):
        """ Compute Z-Score and RSI """
        data = self.history[symbol]
        if not data: return None
        
        current_price = data[-1]
        
        # Z-Score
        try:
            mu = statistics.mean(data)
            sigma = statistics.stdev(data)
        except:
            return None
        
        if sigma == 0: return None
        z_score = (current_price - mu) / sigma
        
        # RSI (Simplified 14)
        if len(data) < 15:
            rsi = 50.0
        else:
            recent_changes = [data[i] - data[i-1] for i in range(len(data)-14, len(data))]
            gains = sum(x for x in recent_changes if x > 0)
            losses = sum(abs(x) for x in recent_changes if x < 0)
            
            if losses == 0: rsi = 100.0
            elif gains == 0: rsi = 0.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            "price": current_price,
            "z_score": z_score,
            "rsi": rsi
        }