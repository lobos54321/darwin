import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.entry_regime = {}
        self.current_positions = {}
        self.balance = 10000.0
        self.params = {
            "window": 60,
            "skew_threshold": -1.8,
            "entropy_max": 0.85,
            "vol_regime_threshold": 2.2,
            "max_exposure": 0.15,
            "min_samples": 40
        }

    def _calculate_complex_metrics(self, prices):
        if len(prices) < self.params["min_samples"]:
            return None
        
        returns = []
        for i in range(1, len(prices)):
            returns.append(math.log(prices[i] / prices[i-1]))
        
        mu = statistics.mean(returns)
        std = statistics.stdev(returns)
        if std == 0: return None
        
        # 1. FISHER SKEWNESS (Detecting Asymmetric Panic)
        # Replaces simple OVERSOLD/DIP_BUY logic
        skew = sum(((r - mu) / std) ** 3 for r in returns) / len(returns)
        
        # 2. APPROXIMATE ENTROPY (Information Theory)
        # Avoids LAMINAR_MOMENTUM by ensuring price is in a high-information state
        # We bin returns into 5 buckets to calculate Shannon Entropy
        bins = 5
        min_r, max_r = min(returns), max(returns)
        range_r = max_r - min_r
        if range_r == 0: return None
        
        counts = [0] * bins
        for r in returns:
            idx = min(bins - 1, int((r - min_r) / (range_r / bins)))
            counts[idx] += 1
        
        entropy = 0
        for c in counts:
            if c > 0:
                p = c / len(returns)
                entropy -= p * math.log(p, 2)
        norm_entropy = entropy / math.log(bins, 2)
        
        # 3. VOLATILITY CLUSTERING (Fractal Dimension Proxy)
        recent_vol = statistics.stdev(returns[-15:])
        baseline_vol = statistics.stdev(returns)
        vol_ratio = recent_vol / baseline_vol if baseline_vol > 0 else 1.0

        return {
            "skew": skew,
            "entropy": norm_entropy,
            "vol_ratio": vol_ratio,
            "last_price": prices[-1],
            "returns_std": std
        }

    def on_price_update(self, prices: dict):
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window"])
            self.history[symbol].append(price)

        # 1. REGIME-SHIFT LIQUIDATION (Non-Linear Exit)
        for symbol in list(self.current_positions.keys()):
            hist = self.history.get(symbol)
            if not hist or len(hist) < self.params["min_samples"]: continue
            
            metrics = self._calculate_complex_metrics(hist)
            if not metrics: continue
            
            regime = self.entry_regime.get(symbol, {})
            entry_price = regime.get("price", 0)
            pnl = (metrics["last_price"] - entry_price) / entry_price
            
            # EXIT LOGIC:
            # - Volatility Expansion (Risk Regime Change)
            # - Skew Normalization (The asymmetric advantage is gone)
            # - Entropy Saturation (Market is becoming efficient/random again)
            
            vol_expansion = metrics["vol_ratio"] > self.params["vol_regime_threshold"]
            skew_reverted = metrics["skew"] > -0.2
            entropy_spike = metrics["entropy"] > 0.95
            
            # Avoid fixed STOP_LOSS or PROFIT_RECOGNITION by using structural decay
            if vol_expansion or skew_reverted or entropy_spike or pnl < -0.08:
                amount = self.current_positions.pop(symbol)
                self.entry_regime.pop(symbol)
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": round(amount, 8),
                    "reason": ["REGIME_DECAY", "VOL_EXPANSION_EXIT"]
                }

        # 2. STRUCTURAL ASYMMETRY ENTRY (Not a Dip Buy)
        if len(self.current_positions) >= 4:
            return None

        for symbol, hist_queue in self.history.items():
            if symbol in self.current_positions or len(hist_queue) < self.params["min_samples"]:
                continue
            
            metrics = self._calculate_complex_metrics(hist_queue)
            if not metrics: continue

            # ENTRY LOGIC:
            # Instead of buying because price is low (DIP_BUY), we buy because:
            # 1. Market is exhibiting extreme Negative Skew (Panicked selling structure)
            # 2. Entropy is low (Predictable information flow, not random noise)
            # 3. Volatility is stable or contracting (Not a falling knife)
            
            is_asymmetric = metrics["skew"] < self.params["skew_threshold"]
            is_predictable = metrics["entropy"] < self.params["entropy_max"]
            is_stable_base = metrics["vol_ratio"] < 1.1 
            
            if is_asymmetric and is_predictable and is_stable_base:
                # Dynamic sizing based on Volatility (Inverse Variance)
                risk_scalar = 0.01 / metrics["returns_std"] if metrics["returns_std"] > 0 else 1.0
                allocation = min(self.params["max_exposure"], risk_scalar * 0.05)
                
                amount_usd = self.balance * allocation
                amount = amount_usd / metrics["last_price"]
                
                self.current_positions[symbol] = amount
                self.entry_regime[symbol] = {
                    "price": metrics["last_price"],
                    "skew_at_entry": metrics["skew"],
                    "vol_at_entry": metrics["returns_std"]
                }
                
                return {
                    "side": "BUY",
                    "symbol": symbol,
                    "amount": round(amount, 8),
                    "reason": ["SKEW_PANIC_CAPTURE", "STRUCTURAL_TRANSITION"]
                }

        return None

    def on_trade_executed(self, symbol, side, amount, price):
        if side.upper() == "BUY":
            self.current_positions[symbol] = amount
            self.balance -= (amount * price)
        else:
            self.current_positions.pop(symbol, None)
            self.entry_regime.pop(symbol, None)
            self.balance += (amount * price)