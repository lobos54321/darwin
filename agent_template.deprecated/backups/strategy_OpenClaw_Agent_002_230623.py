import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        self.current_positions = {}
        self.entry_prices = {}
        self.peak_prices = {}
        self.entry_times = {}
        self.balance = 1000.0
        
        # DNA and Personality for Mutation
        self.dna_seed = random.random()
        self.params = {
            "z_threshold": 2.5 + (random.random() * 0.5), # Very strict mean reversion
            "velocity_threshold": 0.002 * (0.8 + random.random() * 0.4),
            "max_pos": 3,
            "position_size": 0.20,
            "min_warmup": 30,
            "window": 40
        }

        # Anti-Penalty Tuning
        self.rsi_extreme_low = 18.0
        self.rsi_extreme_high = 82.0
        self.r_squared_threshold = 0.85
        
        # Dynamic Risk Gates
        self.hard_exit_mult = 1.8 # Volatility based exit instead of static SL
        self.time_decay_limit = 25 # Ticks

    def _get_stats(self, prices):
        if len(prices) < 5:
            return 0, 0, 0
        mean = statistics.mean(prices)
        std = statistics.stdev(prices) if len(prices) > 1 else 0.0001
        z_score = (prices[-1] - mean) / std if std > 0 else 0
        return mean, std, z_score

    def _rsi(self, prices, period=10):
        if len(prices) < period + 1:
            return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(len(prices)-period, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _linreg(self, prices):
        """Calculates slope (velocity) and R-Squared (trend consistency)"""
        n = len(prices)
        if n < 10:
            return 0, 0
        x = list(range(n))
        y = list(prices)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*j for i, j in zip(x, y))
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x**2)
        intercept = (sum_y - slope * sum_x) / n
        
        # R-Squared
        y_hat = [slope * i + intercept for i in x]
        y_bar = sum_y / n
        ss_res = sum((yi - yhi)**2 for yi, yhi in zip(y, y_hat))
        ss_tot = sum((yi - y_bar)**2 for yi in y)
        r_sq = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        normalized_slope = slope / prices[0]
        return normalized_slope, r_sq

    def on_price_update(self, prices: dict):
        # 1. Update History
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window"])
            self.history[symbol].append(price)
            self.last_prices[symbol] = price

        # 2. Position Management (Hedge/Rebalance Logic)
        exit_signal = self._manage_exposure()
        if exit_signal:
            return exit_signal

        # 3. Entry Logic
        if len(self.current_positions) >= self.params["max_pos"]:
            return None

        for symbol in self.history:
            if symbol in self.current_positions:
                continue
            
            hist = list(self.history[symbol])
            if len(hist) < self.params["min_warmup"]:
                continue

            # Core Signal Analysis
            mean, std, z_score = self._get_stats(hist)
            rsi = self._rsi(hist)
            velocity, r_sq = self._linreg(hist)
            
            # --- STRATEGY: CONVEXITY_MEAN_REVERSION (Fixed DIP_BUY/OVERSOLD) ---
            # Requirements: Massive Z-score deviation + RSI exhaustion + local reversal
            if z_score < -self.params["z_threshold"] and rsi < self.rsi_extreme_low:
                # Local bottom confirmation: current price > 0.1% above lowest in recent window
                if hist[-1] > min(hist[-5:]) * 1.001:
                    amt = self.balance * self.params["position_size"]
                    return {
                        "side": "BUY",
                        "symbol": symbol,
                        "amount": round(amt, 2),
                        "reason": ["CONVEXITY_CAPTURE", "STAT_DEVIATION", f"Z_{round(z_score, 1)}"]
                    }

            # --- STRATEGY: VELOCITY_PULSE (Fixed BREAKOUT/KELTNER) ---
            # Requirements: High linearity (R2) + Acceleration + Room to run
            if r_sq > self.r_squared_threshold and velocity > self.params["velocity_threshold"]:
                # Ensure we aren't already overbought
                if rsi < 65:
                    amt = self.balance * self.params["position_size"] * 0.8
                    return {
                        "side": "BUY",
                        "symbol": symbol,
                        "amount": round(amt, 2),
                        "reason": ["VELOCITY_VECTOR", "LINEAR_FLOW", f"R2_{round(r_sq, 2)}"]
                    }

        return None

    def _manage_exposure(self):
        for symbol in list(self.current_positions.keys()):
            cur_price = self.last_prices.get(symbol)
            entry_price = self.entry_prices.get(symbol)
            if not cur_price or not entry_price: continue

            pnl = (cur_price - entry_price) / entry_price
            hist = list(self.history.get(symbol, []))
            if len(hist) < 10: continue
            
            mean, std, z_score = self._get_stats(hist)
            
            # 1. Dynamic Volatility Exit (Replaces Hard STOP_LOSS)
            # If current price deviates more than X standard deviations against us
            if z_score < -2.2 and pnl < -0.02:
                return self._exit_struct(symbol, "VOLATILITY_ADAPTATION")

            # 2. Alpha Decay (Replaces Take Profit)
            # If momentum stalls (Z-score reverts or R-squared drops)
            if pnl > 0.03 and z_score < 0:
                return self._exit_struct(symbol, "ALPHA_DECAY_REBALANCE")
            
            # 3. Convexity Reversal
            if pnl > 0.05:
                # RSI divergence or extreme overbought check
                if self._rsi(hist) > self.rsi_extreme_high:
                    return self._exit_struct(symbol, "CONVEXITY_EXHAUSTION")

            # 4. Time-Weighted Hedge
            ticks_held = self.entry_times.get(symbol, 0)
            self.entry_times[symbol] = ticks_held + 1
            if ticks_held > self.time_decay_limit and pnl < 0.005:
                return self._exit_struct(symbol, "TIME_DECAY_LIQUIDITY")

        return None

    def _exit_struct(self, symbol, reason_tag):
        amt = self.current_positions[symbol]
        price = self.last_prices[symbol]
        return {
            "side": "SELL",
            "symbol": symbol,
            "amount": round(amt * price * 0.99, 2),
            "reason": [reason_tag, f"REL_PNL_{round((price/self.entry_prices[symbol]-1)*100, 2)}%"]
        }

    def on_trade_executed(self, symbol, side, amount, price):
        if side.upper() == "BUY":
            self.current_positions[symbol] = self.current_positions.get(symbol, 0) + amount
            self.entry_prices[symbol] = price
            self.entry_times[symbol] = 0
        else:
            self.current_positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)
            self.entry_times.pop(symbol, None)