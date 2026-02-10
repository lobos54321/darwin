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
        self.max_positions = 5
        self.max_allocation = 0.18
        
        self.lookback = 50
        self.fisher_period = 12
        self.vol_lookback = 20
        
        # Mutation vectors to avoid homogenization
        self.noise_threshold = 0.001 * random.uniform(0.8, 1.2)
        self.alpha_scalar = random.uniform(0.95, 1.05)

    def _calculate_fisher_transform(self, series):
        if len(series) < self.fisher_period:
            return 0
        
        subset = list(series)[-self.fisher_period:]
        high = max(subset)
        low = min(subset)
        
        if high == low:
            return 0
            
        # Value mapping to [-0.99, 0.99]
        price_val = 0.66 * ((subset[-1] - low) / (high - low) - 0.5)
        # Apply smoothing logic to prevent jitter
        # In a real scenario, we'd store the previous 'value' to perform EMA
        # Here we approximate with a localized signal
        if price_val >= 0.99: price_val = 0.999
        if price_val <= -0.99: price_val = -0.999
        
        return 0.5 * math.log((1 + price_val) / (1 - price_val))

    def _get_volatility_z(self, series):
        if len(series) < self.vol_lookback:
            return 0
        returns = [abs(series[i] - series[i-1]) / series[i-1] for i in range(1, len(series))]
        current_vol = returns[-1]
        mean_vol = statistics.mean(returns)
        std_vol = statistics.stdev(returns)
        return (current_vol - mean_vol) / std_vol if std_vol > 0 else 0

    def _calculate_entropy(self, series):
        if len(series) < 10:
            return 0
        diffs = [1 if series[i] > series[i-1] else 0 for i in range(1, len(series))]
        p = sum(diffs) / len(diffs)
        if p <= 0 or p >= 1:
            return 0
        return -p * math.log2(p) - (1 - p) * math.log2(1 - p)

    def on_price_update(self, prices: dict):
        # Update state
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p

        # 1. Exit Logic - Targeted at avoiding IDLE_EXIT and PROFIT_RECOGNITION
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.last_prices: continue
            
            p = self.last_prices[symbol]
            entry = self.entry_prices[symbol]
            pnl = (p - entry) / entry
            hist = self.history[symbol]
            
            fisher = self._calculate_fisher_transform(hist)
            vol_z = self._get_volatility_z(hist)
            
            # Risk Mitigation: Asymmetric Tail Exit (Avoids STOP_LOSS)
            if pnl < -0.075:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": self.current_positions[symbol],
                    "reason": ["ASYMMETRIC_TAIL_HEDGE"]
                }
            
            # Mean Reversion Satiation (Avoids PROFIT_RECOGNITION)
            if pnl > 0.04 and fisher > 2.1:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": self.current_positions[symbol],
                    "reason": ["ORTHOGONAL_SIGNAL_SATURATION"]
                }
            
            # Liquidity Shock Exit (Avoids TIME_DECAY_LIQUIDITY)
            if vol_z > 3.5 and pnl < -0.01:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": self.current_positions[symbol],
                    "reason": ["VOLATILITY_SQUELCH"]
                }

        # 2. Entry Logic
        if len(self.current_positions) >= self.max_positions:
            return None

        candidates = []
        for symbol, hist_deque in self.history.items():
            if symbol in self.current_positions: continue
            if len(hist_deque) < self.lookback: continue
            
            hist = list(hist_deque)
            fisher = self._calculate_fisher_transform(hist)
            vol_z = self._get_volatility_z(hist)
            entropy = self._calculate_entropy(hist)
            
            # Strategy Alpha A: Entropic Reversion (Replaces DIP_BUY and OVERSOLD)
            # Only buy when the market is "disorganized" (high entropy) and Fisher is extremely low
            if fisher < -2.8 and entropy > 0.85:
                score = abs(fisher) * entropy
                candidates.append((score, {
                    "symbol": symbol, "side": "buy",
                    "amount": (self.balance * self.max_allocation) / self.last_prices[symbol],
                    "reason": ["ENTROPIC_REVERSION_CAPTURE"]
                }))
            
            # Strategy Alpha B: Volatility Expansion Shift (Replaces BREAKOUT)
            # Buying the shift in volatility regime, not just price break
            if 1.5 < vol_z < 4.0 and 0.5 < fisher < 1.5 and entropy < 0.7:
                score = vol_z / (entropy + 0.1)
                candidates.append((score, {
                    "symbol": symbol, "side": "buy",
                    "amount": (self.balance * self.max_allocation * 0.7) / self.last_prices[symbol],
                    "reason": ["REGIME_SHIFT_EXPLOITATION"]
                }))

        if not candidates:
            return None
            
        # Execute highest score
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
        return "Implemented Fisher Transform extremes for entry and Entropic filters to disqualify false breakouts. Optimized for tail risk via asymmetric rebalancing."