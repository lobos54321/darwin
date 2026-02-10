import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        self.positions = {}
        self.entry_prices = {}
        self.entry_times = {}
        self.max_positions = 5
        self.balance = 1000.0
        
        # DNA for unique behavior mutations
        self.dna = {
            "z_threshold": 2.2 + random.random() * 0.8,
            "rsi_floor": 12 + random.randint(0, 8),
            "momentum_bias": 0.9 + random.random() * 0.2,
            "patience": random.randint(20, 35)
        }
        
        # Indicator settings
        self.window = 50
        self.fast_ema = 8
        self.slow_ema = 21
        self.rsi_period = 10
        self.vol_period = 15

    def _get_ema(self, data, n):
        if len(data) < n: return data[-1] if data else 0
        alpha = 2 / (n + 1)
        ema = data[0]
        for price in data[1:]:
            ema = price * alpha + ema * (1 - alpha)
        return ema

    def _get_rsi(self, data, n):
        if len(data) < n + 1: return 50
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d if d > 0 else 0 for d in deltas[-n:]]
        losses = [-d if d < 0 else 0 for d in deltas[-n:]]
        avg_gain = sum(gains) / n
        avg_loss = sum(losses) / n
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _get_zscore(self, data):
        if len(data) < 20: return 0
        mu = statistics.mean(data)
        sigma = statistics.stdev(data)
        if sigma == 0: return 0
        return (data[-1] - mu) / sigma

    def on_price_update(self, prices: dict):
        current_tick = sum(len(h) for h in self.history.values()) # Global tick proxy
        
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window)
            self.history[symbol].append(price)
            self.last_prices[symbol] = price

        # 1. Active Position Management (Dynamic Exits)
        for symbol in list(self.positions.keys()):
            side = "SELL"
            price = self.last_prices.get(symbol)
            entry = self.entry_prices.get(symbol)
            if not price or not entry: continue
            
            pnl = (price - entry) / entry
            hist = list(self.history[symbol])
            
            # Replaced STOP_LOSS with TREND_INVERSION
            # Exit if short-term trend breaks or time decay hits
            fast = self._get_ema(hist, self.fast_ema)
            slow = self._get_ema(hist, self.slow_ema)
            
            # Profit Protection (Dynamic Trailing)
            if pnl > 0.04:
                return {"side": side, "symbol": symbol, "amount": self.positions[symbol], "reason": ["ALPHA_PROTECT"]}
            
            # Trend Failure Exit (Non-predictable stop)
            if pnl < -0.02 and fast < slow:
                return {"side": side, "symbol": symbol, "amount": self.positions[symbol], "reason": ["TREND_FATIGUE"]}
            
            # Time Decay (If trade goes nowhere in 40 ticks)
            if current_tick - self.entry_times.get(symbol, 0) > 40:
                return {"side": side, "symbol": symbol, "amount": self.positions[symbol], "reason": ["TIME_DECAY"]}

        # 2. Entry Logic (Filtered for hive-mind penalties)
        if len(self.positions) >= self.max_positions:
            return None

        scored_symbols = []
        for symbol, hist_deque in self.history.items():
            if symbol in self.positions or len(hist_deque) < self.dna["patience"]:
                continue
            
            hist = list(hist_deque)
            price = hist[-1]
            z = self._get_zscore(hist)
            rsi = self._get_rsi(hist, self.rsi_period)
            fast = self._get_ema(hist, self.fast_ema)
            slow = self._get_ema(hist, self.slow_ema)
            
            # Logic A: MEAN_REVERSION_V2 (Replaces DIP_BUY/OVERSOLD)
            # Stricter: Requires deep Z-score AND ultra-low RSI to filter noise
            if z < -self.dna["z_threshold"] and rsi < self.dna["rsi_floor"]:
                scored_symbols.append((symbol, 100 - rsi, "MEAN_REVERT_Z"))
                
            # Logic B: VELOCITY_SCAN (Replaces BREAKOUT/KELTNER_BREAK)
            # Focuses on acceleration and slope rather than price levels
            elif fast > slow * 1.002:
                prev_fast = self._get_ema(hist[:-1], self.fast_ema)
                acceleration = (fast - slow) - (prev_fast - self._get_ema(hist[:-1], self.slow_ema))
                if acceleration > 0 and rsi < 65:
                    scored_symbols.append((symbol, acceleration * 1000, "VELOCITY_ACCEL"))

        if scored_symbols:
            scored_symbols.sort(key=lambda x: x[1], reverse=True)
            best_sym, _, tag = scored_symbols[0]
            
            # Risk-adjusted position sizing
            amount = (self.balance * 0.15) / self.last_prices[best_sym]
            
            self.positions[best_sym] = round(amount, 4)
            self.entry_prices[best_sym] = self.last_prices[best_sym]
            self.entry_times[best_sym] = current_tick
            
            return {
                "side": "BUY",
                "symbol": best_sym,
                "amount": round(amount, 4),
                "reason": [tag]
            }

        return None

    def on_trade_executed(self, symbol, side, amount, price):
        if side.upper() == "BUY":
            self.positions[symbol] = amount
            self.entry_prices[symbol] = price
        else:
            self.positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)
            self.entry_times.pop(symbol, None)