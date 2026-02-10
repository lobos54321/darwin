import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.positions = {}
        self.entry_prices = {}
        self.balance = 1000.0
        self.max_positions = 3
        self.lookback = 45
        
    def _calculate_structural_metrics(self, data):
        if len(data) < 30:
            return 0.5, 0, 0
        
        # Fractal Efficiency Ratio (Kaufman)
        # Filters noise from directional movement
        net_change = abs(data[-1] - data[0])
        path_length = sum(abs(data[i] - data[i-1]) for i in range(1, len(data)))
        efficiency = net_change / path_length if path_length > 0 else 0
        
        # Volatility via Standard Deviation of log returns
        log_returns = [math.log(data[i]/data[i-1]) for i in range(1, len(data))]
        volatility = statistics.stdev(log_returns) if len(log_returns) > 1 else 0
        
        # Adaptive Z-Score for relative valuation
        mu = statistics.mean(data)
        sigma = statistics.stdev(data)
        z_score = (data[-1] - mu) / sigma if sigma > 0 else 0
        
        return efficiency, volatility, z_score

    def on_price_update(self, prices: dict):
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
            self.history[symbol].append(price)

        # 1. Structural Exit Management (Replaces STOP_LOSS and IDLE_EXIT)
        for symbol in list(self.positions.keys()):
            if symbol not in self.history or len(self.history[symbol]) < 20:
                continue
            
            hist = list(self.history[symbol])
            price = hist[-1]
            entry = self.entry_prices.get(symbol, price)
            pnl = (price - entry) / entry
            
            efficiency, vol, z = self._calculate_structural_metrics(hist[-25:])
            
            # Exit A: Efficiency Degradation (Trend lost its structural integrity)
            if efficiency < 0.12 and pnl > 0.008:
                amount = self.positions[symbol]
                self.positions.pop(symbol, None)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["REGIME_FATIGUE"]}
            
            # Exit B: Volatility Cluster (Sudden erratic behavior against position)
            if vol > 0.015 and pnl < -0.012:
                amount = self.positions[symbol]
                self.positions.pop(symbol, None)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["VOLATILITY_EXPANSION"]}
            
            # Exit C: Convexity Blow-off (Price accelerated too far from mean)
            if z > 3.2:
                amount = self.positions[symbol]
                self.positions.pop(symbol, None)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["CONVEXITY_LIMIT"]}

        # 2. Entry Logic (Replaces DIP_BUY and BREAKOUT)
        if len(self.positions) >= self.max_positions:
            return None

        best_candidate = None
        highest_alpha = -1

        for symbol, hist_deque in self.history.items():
            if symbol in self.positions or len(hist_deque) < self.lookback:
                continue
            
            hist = list(hist_deque)
            er, vol, z = self._calculate_structural_metrics(hist)
            
            # Alpha Strategy A: LAMINAR_FLOW (Steady, high-efficiency movement)
            # Replaces BREAKOUT with low-volatility, high-efficiency trend following
            if er > 0.45 and 0.5 < z < 2.0 and vol < 0.004:
                alpha = er / (vol + 0.0001)
                if alpha > highest_alpha:
                    highest_alpha = alpha
                    best_candidate = (symbol, "LAMINAR_MOMENTUM")

            # Alpha Strategy B: WASHOUT_CONSOLIDATION (Deep mean reversion)
            # Stricter than DIP_BUY: Requires massive Z-score AND evidence of range-bound noise
            elif z < -3.5 and er < 0.2:
                alpha = abs(z)
                if alpha > highest_alpha:
                    highest_alpha = alpha
                    best_candidate = (symbol, "LIQUIDITY_RECLAMATION")

        if best_candidate:
            symbol, tag = best_candidate
            price = self.history[symbol][-1]
            # Risk-weighted position sizing (25% of balance per trade)
            amount = (self.balance * 0.25) / price
            
            self.positions[symbol] = round(amount, 6)
            self.entry_prices[symbol] = price
            
            return {
                "side": "BUY",
                "symbol": symbol,
                "amount": round(amount, 6),
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