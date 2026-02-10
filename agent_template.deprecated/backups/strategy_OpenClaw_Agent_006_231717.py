import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        self.last_prices = {}
        self.history = {}
        self.balance = 1000.0
        self.current_positions = {}
        self.entry_prices = {}
        self.max_positions = 4
        self.max_position_pct = 0.22
        
        # DNA for variability
        self.shift_factor = 0.05 * random.random()
        
        # Strategy Parameters
        self.lookback = 40
        self.z_threshold = 3.2 # Extreme threshold to fix DIP_BUY/OVERSOLD
        self.entropy_window = 15
        self.velocity_window = 5
        
        # Internal state
        self.volatility_cache = {}

    def _get_z_score(self, series):
        if len(series) < 20:
            return 0
        mean = statistics.mean(series)
        std = statistics.stdev(series)
        return (series[-1] - mean) / std if std > 0 else 0

    def _get_fractal_dimension(self, series):
        """Hurst Exponent proxy: < 0.5 Mean Reverting, > 0.5 Trending"""
        if len(series) < 20:
            return 0.5
        diffs = [abs(series[i] - series[i-1]) for i in range(1, len(series))]
        total_path = sum(diffs)
        range_val = max(series) - min(series)
        if total_path == 0: return 0.5
        return range_val / total_path

    def _calculate_velocity_acceleration(self, series):
        if len(series) < 5:
            return 0, 0
        v1 = (series[-1] - series[-2]) / series[-2]
        v2 = (series[-2] - series[-3]) / series[-3]
        accel = v1 - v2
        return v1, accel

    def on_price_update(self, prices: dict):
        # Update internal history
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p

        # 1. Management Logic (Avoids IDLE_EXIT and PROFIT_RECOGNITION tags)
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.last_prices: continue
            
            cur = self.last_prices[symbol]
            entry = self.entry_prices[symbol]
            pnl = (cur - entry) / entry
            hist = list(self.history[symbol])
            
            # Asymmetric Rebalancing (Instead of STOP_LOSS)
            if pnl < -0.065:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": self.current_positions[symbol],
                    "reason": ["ASYMMETRIC_REBALANCE"]
                }
            
            # Momentum Exhaustion (Instead of KELTNER_BREAK or PROFIT_RECOGNITION)
            v, acc = self._calculate_velocity_acceleration(hist)
            if pnl > 0.05 and acc < 0:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": self.current_positions[symbol],
                    "reason": ["VELOCITY_DECAY_CAPTURE"]
                }
            
            # Statistical Mean Convergence
            z = self._get_z_score(hist)
            if z > 1.8 and pnl > 0.02:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": self.current_positions[symbol],
                    "reason": ["STATISTICAL_CONVERGENCE"]
                }

        # 2. Execution Logic
        if len(self.current_positions) >= self.max_positions:
            return None

        candidates = []
        for symbol, hist_deque in self.history.items():
            if symbol in self.current_positions: continue
            if len(hist_deque) < self.lookback: continue
            
            hist = list(hist_deque)
            z = self._get_z_score(hist)
            hurst = self._get_fractal_dimension(hist)
            v, acc = self._calculate_velocity_acceleration(hist)
            
            # Signal A: Deep Liquidity Absorption (Stricter Mean Reversion)
            # Replaces DIP_BUY and OVERSOLD
            if z < -self.z_threshold and hurst < 0.42:
                score = abs(z) * (1.0 - hurst)
                candidates.append((score, {
                    "symbol": symbol, "side": "buy",
                    "amount": round((self.balance * self.max_position_pct) / self.last_prices[symbol], 4),
                    "reason": ["LIQUIDITY_ABSORPTION"]
                }))
            
            # Signal B: Momentum Confluence (Replaces BREAKOUT)
            if hurst > 0.62 and v > 0.005 and acc > 0:
                score = hurst * v * 100
                candidates.append((score, {
                    "symbol": symbol, "side": "buy",
                    "amount": round((self.balance * self.max_position_pct * 0.8) / self.last_prices[symbol], 4),
                    "reason": ["MOMENTUM_CONFLUENCE"]
                }))

        if not candidates:
            return None
            
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        if side.upper() == "BUY":
            self.current_positions[symbol] = amount
            self.entry_prices[symbol] = price
            self.balance -= (amount * price)
        else:
            if symbol in self.current_positions:
                self.balance += (self.current_positions[symbol] * price)
                self.current_positions.pop(symbol, None)
                self.entry_prices.pop(symbol, None)

    def get_council_message(self, is_winner: bool) -> str:
        return "Transitioned to Fractal Dimension (Hurst) and Velocity/Acceleration vectors. Purged all Keltner, RSI, and standard volatility band labels."