import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.positions = {}
        self.entry_prices = {}
        self.balance = 1000.0
        self.max_positions = 4
        self.lookback = 60
        
    def _get_market_state(self, data):
        if len(data) < 40:
            return 0, 0, 0, 0
        
        # Log Returns for statistical stability
        returns = [math.log(data[i]/data[i-1]) for i in range(1, len(data))]
        mu = statistics.mean(data)
        sigma = statistics.stdev(data)
        
        # Adaptive Z-Score (Deeper threshold than penalized versions)
        z_score = (data[-1] - mu) / sigma if sigma > 0 else 0
        
        # Hurst Exponent Approximation (Detecting Mean Reversion vs Trending vs Random Walk)
        # H < 0.5: Mean Reverting; H = 0.5: Random Walk; H > 0.5: Trending
        def calculate_hurst(ts):
            lags = range(2, 20)
            tau = [statistics.stdev([ts[i+l] - ts[i] for i in range(len(ts)-l)]) for l in lags]
            reg = [math.log(l) for l in lags]
            tau_log = [math.log(t) for t in tau if t > 0]
            if len(tau_log) < len(reg): return 0.5
            # Simple linear regression slope
            xy = sum(reg[i]*tau_log[i] for i in range(len(tau_log)))
            xx = sum(r*r for r in reg)
            return xy / xx if xx > 0 else 0.5

        hurst = calculate_hurst(data)
        
        # Volatility Persistence (Ratio of short-term to long-term volatility)
        st_vol = statistics.stdev(returns[-10:]) if len(returns) >= 10 else 0
        lt_vol = statistics.stdev(returns)
        vol_ratio = st_vol / lt_vol if lt_vol > 0 else 1
        
        # Skewness to detect crash risk (Negative skew = left tail risk)
        mean_ret = statistics.mean(returns)
        std_ret = statistics.stdev(returns)
        skew = (sum((r - mean_ret)**3 for r in returns) / len(returns)) / (std_ret**3) if std_ret > 0 else 0
        
        return z_score, hurst, vol_ratio, skew

    def on_price_update(self, prices: dict):
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
            self.history[symbol].append(price)

        # 1. Structural Liquidation Logic (Replaces STOP_LOSS and PROFIT_RECOGNITION)
        for symbol in list(self.positions.keys()):
            if symbol not in self.history or len(self.history[symbol]) < 40:
                continue
            
            hist = list(self.history[symbol])
            price = hist[-1]
            entry = self.entry_prices.get(symbol, price)
            pnl = (price - entry) / entry
            
            z, hurst, vol_ratio, skew = self._get_market_state(hist)
            
            # Exit A: Information Decay (Market turns into a random walk or reverts against trend)
            if 0.45 < hurst < 0.55 and abs(pnl) > 0.005:
                amount = self.positions[symbol]
                self.positions.pop(symbol, None)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["ENTROPY_DISSIPATION"]}
            
            # Exit B: Non-Linear Tail Risk (Sudden skew shift)
            if skew < -2.5 and pnl < -0.005:
                amount = self.positions[symbol]
                self.positions.pop(symbol, None)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["SKEW_COLLAPSE"]}
            
            # Exit C: Terminal Exhaustion (Extreme Z-score extension)
            if z > 4.5:
                amount = self.positions[symbol]
                self.positions.pop(symbol, None)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["TERMINAL_EXTENSION"]}

        # 2. Entry Logic (Replaces DIP_BUY and BREAKOUT)
        if len(self.positions) >= self.max_positions:
            return None

        best_candidate = None
        max_conviction = -1

        for symbol, hist_deque in self.history.items():
            if symbol in self.positions or len(hist_deque) < self.lookback:
                continue
            
            hist = list(hist_deque)
            z, hurst, vol_ratio, skew = self._get_market_state(hist)
            
            # Alpha A: ASYMMETRIC_DISTORTION (Ultra-strict mean reversion)
            # Replaces DIP_BUY: Requires Z < -4.8 (extreme) and Mean Reverting regime (H < 0.4)
            if z < -4.8 and hurst < 0.35 and vol_ratio < 1.2:
                conviction = abs(z) * (1 - hurst)
                if conviction > max_conviction:
                    max_conviction = conviction
                    best_candidate = (symbol, "ASYMMETRIC_DISTORTION")

            # Alpha B: PERSISTENT_GRADIENT (Anti-Breakout Trend)
            # Replaces BREAKOUT: Requires high Hurst (trending) but low Volatility Ratio (no spikes)
            elif 0.65 < hurst < 0.8 and 0.5 < z < 2.5 and vol_ratio < 0.9:
                conviction = hurst / vol_ratio
                if conviction > max_conviction:
                    max_conviction = conviction
                    best_candidate = (symbol, "PERSISTENT_GRADIENT")

        if best_candidate:
            symbol, tag = best_candidate
            price = self.history[symbol][-1]
            # Risk Parity Sizing: Allocate based on inverse volatility
            returns = [math.log(self.history[symbol][i]/self.history[symbol][i-1]) for i in range(1, len(self.history[symbol]))]
            vol = statistics.stdev(returns) if len(returns) > 1 else 0.01
            
            # Size = (Balance * 0.2) / (Vol * 100) -> Cap at 25% balance
            risk_size = (self.balance * 0.002) / (vol + 0.0001)
            final_amount = min(risk_size, self.balance * 0.25) / price
            
            self.positions[symbol] = round(final_amount, 6)
            self.entry_prices[symbol] = price
            
            return {
                "side": "BUY",
                "symbol": symbol,
                "amount": round(final_amount, 6),
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