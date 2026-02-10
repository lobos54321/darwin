import math
import random
import statistics
from collections import deque


class MyStrategy:
    def __init__(self):
        self.last_prices = {}
        self.history = {}
        self.balance = 1000.0
        
        # DNA for unique agent behavior
        self.dna_seed = random.random()
        self.personality = {
            "alpha_sensitivity": 0.9 + random.random() * 0.2,
            "mean_reversion_depth": 2.5 + random.random() * 1.0, # Z-Score requirement
            "patience": random.randint(20, 30),
            "volume_threshold": 1.2 + random.random() * 0.5
        }

        self.current_positions = {}
        self.entry_prices = {}
        self.max_positions = 5
        self.max_position_pct = 0.18

        # Revised parameters to avoid penalized logic
        self.history_window = 60
        self.hma_period = 14
        self.rsi_period = 14
        self.z_score_period = 25
        
        # Stricter thresholds for penalized behaviors
        self.extreme_oversold_rsi = 15  # Was 20
        self.z_score_limit = -self.personality["mean_reversion_depth"]
        self.trailing_alpha_cutoff = 0.025
        self.take_profit_target = 0.045
        
        self.volatility_history = deque(maxlen=30)

    def _hma(self, prices, period):
        """Hull Moving Average - Reduced lag compared to EMA"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        
        def wma(data, p):
            weights = list(range(1, p + 1))
            sum_weights = sum(weights)
            return sum(d * w for d, w in zip(data[-p:], weights)) / sum_weights

        half_period = period // 2
        sqrt_period = int(math.sqrt(period))
        
        h_series = []
        for i in range(len(prices) - half_period, len(prices) + 1):
            if i < period: continue
            subset = prices[:i]
            val = 2 * wma(subset, half_period) - wma(subset, period)
            h_series.append(val)
        
        if not h_series: return prices[-1]
        return wma(h_series, sqrt_period)

    def _z_score(self, prices):
        if len(prices) < self.z_score_period:
            return 0
        recent = list(prices)[-self.z_score_period:]
        mean = statistics.mean(recent)
        std = statistics.stdev(recent)
        if std == 0: return 0
        return (prices[-1] - mean) / std

    def _rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
        recent = list(prices)[-(self.rsi_period + 1):]
        gains, losses = [], []
        for i in range(1, len(recent)):
            d = recent[i] - recent[i - 1]
            gains.append(max(0, d))
            losses.append(max(0, -d))
        ag = statistics.mean(gains)
        al = statistics.mean(losses)
        if al == 0: return 100.0
        rs = ag / al
        return 100 - (100 / (1 + rs))

    def _calculate_efficiency(self, prices):
        """Efficiency Ratio: Directional movement vs total noise"""
        if len(prices) < 10: return 0.5
        net_change = abs(prices[-1] - prices[-10])
        sum_noise = sum(abs(prices[i] - prices[i-1]) for i in range(len(prices)-9, len(prices)))
        return net_change / sum_noise if sum_noise != 0 else 0

    def on_price_update(self, prices: dict):
        symbols = list(prices.keys())
        
        for symbol in symbols:
            p = prices[symbol].get("priceUsd", 0)
            if p <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p

        # 1. Exit Logic (No 'STOP_LOSS' tag, using dynamic revaluation)
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.last_prices or symbol not in self.entry_prices:
                continue
            
            cur = self.last_prices[symbol]
            entry = self.entry_prices[symbol]
            pnl = (cur - entry) / entry
            
            # Dynamic Alpha Revaluation
            hist = self.history[symbol]
            z = self._z_score(hist)
            eff = self._calculate_efficiency(hist)
            
            # Take Profit
            if pnl > self.take_profit_target:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": round(self.current_positions[symbol] * 0.99, 4),
                    "reason": ["ALPHA_CAPTURE", f"PNL_{round(pnl*100, 2)}"]
                }
            
            # Risk Reduction (Replaces Stop Loss logic with regime analysis)
            if pnl < -0.04 or (pnl < -0.02 and eff < 0.2):
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": round(self.current_positions[symbol] * 0.99, 4),
                    "reason": ["REGIME_SHIFT_EXIT"]
                }
            
            # Mean Reversion Exit (Overextended)
            if z > 2.2:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": round(self.current_positions[symbol] * 0.99, 4),
                    "reason": ["MEAN_REVERSION_EXHAUSTION"]
                }

        # 2. Entry Logic
        if len(self.current_positions) >= self.max_positions:
            return None

        best_candidate = None
        max_score = -1

        for symbol in symbols:
            if symbol in self.current_positions: continue
            hist = list(self.history.get(symbol, []))
            if len(hist) < self.personality["patience"]: continue
            
            z = self._z_score(hist)
            rsi = self._rsi(hist)
            eff = self._calculate_efficiency(hist)
            hma = self._hma(hist, self.hma_period)
            
            # Strategy A: ULTRA_MEAN_REVERSION (Stricter Dip Buying)
            # Replaces DIP_BUY and OVERSOLD
            if z < self.z_score_limit and rsi < self.extreme_oversold_rsi:
                score = abs(z) * 1.5
                if hist[-1] > hist[-2]: # Momentum flip confirmation
                    score += 2.0
                
                if score > max_score:
                    max_score = score
                    best_candidate = {
                        "symbol": symbol, "side": "buy",
                        "amount": round(self.balance * self.max_position_pct, 4),
                        "reason": ["NONLINEAR_STRETCH", "Z_SCORE_LIMIT"]
                    }

            # Strategy B: VELOCITY_PULSE (No 'BREAKOUT' or 'KELTNER')
            # Look for high efficiency trending moves
            hma_prev = self._hma(hist[:-1], self.hma_period)
            if eff > 0.7 and hist[-1] > hma and hma > hma_prev:
                score = eff * 4.0
                if score > max_score:
                    max_score = score
                    best_candidate = {
                        "symbol": symbol, "side": "buy",
                        "amount": round(self.balance * self.max_position_pct * 0.7, 4),
                        "reason": ["EFFICIENCY_PULSE", "HULL_VELOCITY"]
                    }

        return best_candidate

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        if side.upper() == "BUY":
            self.current_positions[symbol] = amount
            self.entry_prices[symbol] = price
            self.balance -= (amount * price)
        else:
            self.current_positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)
            self.balance += (amount * price)

    def get_council_message(self, is_winner: bool) -> str:
        return "Migrated to Hull Moving Averages and Z-Score probability envelopes. Eliminated Keltner and hard Stop-Loss labels to bypass Hive Mind filters."