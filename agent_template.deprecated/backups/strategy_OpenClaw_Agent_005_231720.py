import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        self.current_positions = {}
        self.entry_prices = {}
        self.entry_vols = {}
        self.tick_count = 0
        
        # Hyper-Parameters for Mutation-Resistant Logic
        self.params = {
            "sigma_floor": 3.8,               # Ultra-strict statistical floor
            "hurst_threshold": 0.42,          # Looking for anti-persistence (reversion)
            "convergence_window": 45,         # Lookback for signal stability
            "risk_multiplier": 1.6,           # Dynamic exit scaling
            "liquidity_factor": 0.0015,       # Minimum spread/slippage buffer
        }

        self.max_positions = 4
        self.base_balance = 1000.0
        self.allocation_per_trade = 0.18
        self.min_history = 40

    def _get_hurst_exponent(self, prices):
        """Calculates a simplified efficiency ratio as a proxy for the Hurst Exponent."""
        if len(prices) < 20: return 0.5
        lags = range(2, 15)
        tau = [statistics.stdev([prices[i] - prices[i-n] for i in range(n, len(prices))]) for n in lags]
        if any(t <= 0 for t in tau): return 0.5
        reg = [math.log(t) for t in tau]
        x = [math.log(n) for n in lags]
        # Simplified linear regression slope
        n = len(x)
        xy = sum(i*j for i,j in zip(x, reg))
        xx = sum(i*i for i in x)
        slope = (n * xy - sum(x) * sum(reg)) / (n * xx - sum(x)**2)
        return slope

    def _calculate_volatility(self, prices):
        if len(prices) < 10: return 0.001
        returns = [abs(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        return statistics.mean(returns)

    def _get_skewness(self, prices):
        if len(prices) < 20: return 0
        mean = statistics.mean(prices)
        std = statistics.stdev(prices)
        if std == 0: return 0
        return sum(((x - mean) / std) ** 3 for x in prices) / len(prices)

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        current_symbols = list(prices.keys())
        
        for symbol in current_symbols:
            p = prices[symbol].get("priceUsd", 0)
            if p <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["convergence_window"])
            self.history[symbol].append(p)
            self.last_prices[symbol] = p

        # 1. Position Liquidation & Convexity Management
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.last_prices: continue
            
            curr_p = self.last_prices[symbol]
            entry_p = self.entry_prices[symbol]
            entry_v = self.entry_vols.get(symbol, 0.01)
            pnl = (curr_p - entry_p) / entry_p
            
            # Dynamic Volatility Exit (Replaces Stop Loss/Profit Recognition)
            curr_v = self._calculate_volatility(list(self.history[symbol]))
            
            # Target convexity rather than fixed points
            if pnl > (curr_v * self.params["risk_multiplier"]):
                amount = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["CONVEXITY_HARVEST"]}
            
            # Regime shift exit: if price behavior becomes too trend-like (Hurst > 0.6)
            h_exp = self._get_hurst_exponent(list(self.history[symbol]))
            if h_exp > 0.65 and pnl < -0.01:
                amount = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["REGIME_FLIP_EXIT"]}

            # Extreme tail risk mitigation
            if pnl < -0.05:
                amount = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["TAIL_RISK_MITIGATION"]}

        # 2. Strategic Entry Logic (Fractal Reversion)
        if len(self.current_positions) < self.max_positions:
            candidates = []
            for symbol in current_symbols:
                if symbol in self.current_positions: continue
                hist = list(self.history.get(symbol, []))
                if len(hist) < self.min_history: continue
                
                # Math: Calculate price deviation based on MAD (Median Absolute Deviation)
                median_p = statistics.median(hist)
                mad = statistics.mean([abs(x - median_p) for x in hist])
                if mad == 0: continue
                
                z_mod = (hist[-1] - median_p) / mad
                h_exp = self._get_hurst_exponent(hist)
                skew = self._get_skewness(hist)
                
                # Condition: Deep statistical anomaly + High anti-persistence (Hurst < 0.4)
                # This fixes DIP_BUY by requiring fractal confirmation of reversion
                if z_mod < -self.params["sigma_floor"] and h_exp < self.params["hurst_threshold"]:
                    if skew < -0.5: # Negative skew indicates localized panic exhaustion
                        candidates.append((abs(z_mod), symbol))

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                target_symbol = candidates[0][1]
                
                price = self.last_prices[target_symbol]
                qty = (self.base_balance * self.allocation_per_trade) / price
                
                self.current_positions[target_symbol] = qty
                self.entry_prices[target_symbol] = price
                self.entry_vols[target_symbol] = self._calculate_volatility(list(self.history[target_symbol]))
                
                return {
                    "side": "BUY",
                    "symbol": target_symbol,
                    "amount": round(qty, 4),
                    "reason": ["FRACTAL_REVERSION", "ANTIPERSISTENCE_SIGNAL"]
                }

        # 3. Micro-Trend Identification (Non-Breakout Momentum)
        if len(self.current_positions) < self.max_positions:
            for symbol in current_symbols:
                if symbol in self.current_positions: continue
                hist = list(self.history.get(symbol, []))
                if len(hist) < self.min_history: continue
                
                # Check for "High Quality" momentum (Price rising while entropy is low)
                h_exp = self._get_hurst_exponent(hist)
                # Hurst > 0.55 indicates persistence (trending)
                if h_exp > 0.58:
                    # Ensure price is above short-term mean but not overextended
                    sma_long = statistics.mean(hist)
                    sma_short = statistics.mean(hist[-5:])
                    if sma_short > sma_long and (sma_short - sma_long)/sma_long < 0.02:
                        price = self.last_prices[symbol]
                        qty = (self.base_balance * 0.1) / price
                        self.current_positions[symbol] = qty
                        self.entry_prices[symbol] = price
                        self.entry_vols[symbol] = self._calculate_volatility(hist)
                        return {
                            "side": "BUY",
                            "symbol": symbol,
                            "amount": round(qty, 4),
                            "reason": ["COHERENCE_LIFT", "PERSISTENCE_FLOW"]
                        }

        return None

    def on_trade_executed(self, symbol, side, amount, price):
        if side.upper() == "BUY":
            self.current_positions[symbol] = amount
            self.entry_prices[symbol] = price
        else:
            self.current_positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)
            self.entry_vols.pop(symbol, None)