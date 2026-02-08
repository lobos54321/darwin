import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.balance = 1000.0
        self.positions = {}
        self.history = {}
        
        # === Strategy: Donchian Volatility Breakout ===
        # REWRITE GOAL: Eliminate 'MEAN_REVERSION' penalty.
        # METHOD: Pure Trend Following via Donchian Channels.
        # LOGIC: 
        #   1. Entry: Price breaks above the Highest High of the last 30 ticks.
        #      (Strictly buying strength/new highs, never dips).
        #   2. Exit: Price breaks below the Lowest Low of the last 15 ticks.
        #      (Trailing Stop Loss structure).
        #   3. Filter: Volatility must be expanding to confirm the move isn't noise.
        
        self.params = {
            "window_entry": 30,        # Lookback for Breakout High
            "window_exit": 15,         # Lookback for Trailing Stop Low
            "min_liq": 10_000_000.0,   # Liquidity Floor
            "min_vol": 2_500_000.0,    # Volume Floor
            "pos_limit": 5,            # Max portfolio slots
            "min_volatility": 0.0005,  # Min volatility (stddev/mean) to trade
        }

    def _calculate_metrics(self, price_deque):
        """
        Calculates Donchian Channel metrics and Volatility.
        Returns None if insufficient data.
        """
        # Need full window + current tick
        if len(price_deque) < self.params["window_entry"]:
            return None
            
        prices = list(price_deque)
        current_price = prices[-1]
        
        # Historical data (excluding current tick for breakout references)
        # We look at the window preceding the current tick to define "Previous High/Low"
        history_window = prices[:-1]
        
        # 1. Donchian Entry Level (Highest High of previous N)
        entry_slice = history_window[-self.params["window_entry"]:]
        highest_high = max(entry_slice)
        
        # 2. Donchian Exit Level (Lowest Low of previous M)
        exit_slice = history_window[-self.params["window_exit"]:]
        lowest_low = min(exit_slice)
        
        # 3. Volatility (Standard Deviation of the entry window)
        # Measures if the asset is active enough to sustain a trend
        mean_p = sum(entry_slice) / len(entry_slice)
        variance = sum((p - mean_p) ** 2 for p in entry_slice) / len(entry_slice)
        volatility = math.sqrt(variance) / mean_p
        
        return {
            "current_price": current_price,
            "highest_high": highest_high,
            "lowest_low": lowest_low,
            "volatility": volatility,
            "is_breakout": current_price > highest_high,
            "is_breakdown": current_price < lowest_low
        }

    def on_price_update(self, prices):
        candidates = []
        
        # 1. Update Data & Calculate Metrics
        for symbol, data in prices.items():
            try:
                price = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Anti-EXPLORE Filters
            if liq < self.params["min_liq"] or vol < self.params["min_vol"]:
                continue
                
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window_entry"] + 5)
            self.history[symbol].append(price)
            
            # Calculate Metrics
            metrics = self._calculate_metrics(self.history[symbol])
            if metrics:
                candidates.append({
                    "symbol": symbol,
                    "metrics": metrics
                })
        
        # 2. Position Management (Exits)
        # Iterate copy of keys to allow deletion during iteration
        for symbol in list(self.positions.keys()):
            pos_info = self.positions[symbol]
            market_data = next((c for c in candidates if c["symbol"] == symbol), None)
            
            should_sell = False
            reason = ""
            
            if not market_data:
                should_sell = True
                reason = "ELIGIBILITY_LOST"
            else:
                m = market_data["metrics"]
                
                # A. Donchian Trailing Stop (Breakdown)
                # If price falls below the recent low, the trend is invalidated.
                if m["is_breakdown"]:
                    should_sell = True
                    reason = "DONCHIAN_BREAKDOWN"
                
                # B. Stagnation Exit
                # If volatility drops too low, the breakout failed or trend stalled.
                elif m["volatility"] < (self.params["min_volatility"] * 0.5):
                    should_sell = True
                    reason = "VOLATILITY_COLLAPSE"
            
            if should_sell:
                amount = pos_info["amount"]
                del self.positions[symbol]
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": amount,
                    "reason": [reason]
                }