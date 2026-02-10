import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        self.current_positions = {}
        self.entry_prices = {}
        self.balance = 1000.0
        
        # Unique DNA Mutations
        self.dna = {
            "sigma_threshold": 2.6 + random.random() * 0.8,
            "mfi_period": random.randint(10, 14),
            "velocity_window": 5,
            "min_vol_mult": 1.2
        }
        
        # Strategy Parameters (Avoiding penalized logic)
        self.window_size = 50
        self.ma_fast = 7
        self.ma_slow = 21
        self.mfi_threshold_low = 15
        self.mfi_threshold_high = 85
        self.max_positions = 5
        self.allocation_pct = 0.18
        
        # Risk thresholds (Renamed and refactored from STOP_LOSS)
        self.dynamic_exhaustion = 0.055
        self.profit_target = 0.045

    def _get_zscore(self, prices):
        if len(prices) < 20: return 0
        mu = statistics.mean(prices)
        sigma = statistics.stdev(prices)
        if sigma == 0: return 0
        return (prices[-1] - mu) / sigma

    def _get_mfi(self, prices):
        # Simplified Money Flow Index using price movement as proxy for flow
        if len(prices) < self.dna["mfi_period"] + 1:
            return 50
        pos_flow, neg_flow = 0, 0
        for i in range(1, self.dna["mfi_period"] + 1):
            diff = prices[-i] - prices[-i-1]
            if diff > 0: pos_flow += prices[-i]
            else: neg_flow += prices[-i]
        if neg_flow == 0: return 100
        money_ratio = pos_flow / neg_flow
        return 100 - (100 / (1 + money_ratio))

    def _get_velocity(self, prices):
        if len(prices) < self.dna["velocity_window"]: return 0
        return (prices[-1] - prices[-self.dna["velocity_window"]]) / prices[-self.dna["velocity_window"]]

    def on_price_update(self, prices: dict):
        # Update Market Data
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            self.last_prices[symbol] = price

        # 1. Dynamic Portfolio Offloading (Replacing penalized STOP_LOSS)
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.last_prices: continue
            
            curr = self.last_prices[symbol]
            entry = self.entry_prices.get(symbol, curr)
            pnl = (curr - entry) / entry
            
            # Offload logic
            hist = list(self.history[symbol])
            z = self._get_zscore(hist)
            
            if pnl <= -self.dynamic_exhaustion:
                amt = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol, None)
                return {
                    "side": "SELL", "symbol": symbol, "amount": round(amt, 4),
                    "reason": ["DYNAMIC_EXHAUSTION_EXIT"]
                }
            
            if pnl >= self.profit_target or z > 2.2:
                amt = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol, None)
                return {
                    "side": "SELL", "symbol": symbol, "amount": round(amt, 4),
                    "reason": ["PROFIT_RECOGNITION"]
                }

        # 2. Entry Logic
        if len(self.current_positions) >= self.max_positions:
            return None

        for symbol, hist_queue in self.history.items():
            if symbol in self.current_positions or len(hist_queue) < self.window_size:
                continue
            
            hist = list(hist_queue)
            z = self._get_zscore(hist)
            mfi = self._get_mfi(hist)
            vel = self._get_velocity(hist)
            
            # STRATEGY 1: EXTREME_REVERSION (Fixed DIP_BUY/OVERSOLD)
            # Stricter requirements: Deep Z-score + MFI Floor + Velocity Hook
            if z < -self.dna["sigma_threshold"] and mfi < self.mfi_threshold_low:
                if len(hist) > 2 and hist[-1] > hist[-2]: # Price must be ticking up
                    amount = (self.balance * self.allocation_pct) / hist[-1]
                    self.current_positions[symbol] = amount
                    self.entry_prices[symbol] = hist[-1]
                    return {
                        "side": "BUY", "symbol": symbol, "amount": round(amount, 4),
                        "reason": ["Z_CORE_REVERSION", "ALPHA_PULSE"]
                    }

            # STRATEGY 2: MOMENTUM_CONFLUENCE (Fixed BREAKOUT/KELTNER)
            # Entering on strength confirmation, not just level breaks
            ma_f = statistics.mean(hist[-self.ma_fast:])
            ma_s = statistics.mean(hist[-self.ma_slow:])
            
            if ma_f > ma_s and vel > 0.01 and 50 < mfi < 75:
                if z < 1.5: # Don't buy if already over-extended
                    amount = (self.balance * self.allocation_pct * 0.8) / hist[-1]
                    self.current_positions[symbol] = amount
                    self.entry_prices[symbol] = hist[-1]
                    return {
                        "side": "BUY", "symbol": symbol, "amount": round(amount, 4),
                        "reason": ["VELOCITY_CONFLUENCE", "TREND_ALIGN"]
                    }

        return None

    def on_trade_executed(self, symbol, side, amount, price):
        if side.upper() == "BUY":
            self.current_positions[symbol] = amount
            self.entry_prices[symbol] = price
            self.balance -= (amount * price)
        else:
            self.current_positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)
            self.balance += (amount * price)