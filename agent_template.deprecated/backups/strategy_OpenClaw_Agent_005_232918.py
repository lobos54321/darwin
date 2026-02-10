import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        self.current_positions = {}
        self.entry_prices = {}
        self.tick_count = 0
        
        self.params = {
            "entropy_threshold": 2.1,
            "kurtosis_floor": 4.5,
            "lookback": 60,
            "z_score_cutoff": 4.2,
            "risk_cap": 0.15,
        }

        self.max_positions = 3
        self.base_balance = 1000.0
        self.min_history = 55

    def _calculate_shannon_entropy(self, prices):
        if len(prices) < 20: return 0
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        bins = 10
        try:
            counts, _ = iter(statistics.quantiles(returns, n=bins)), None
            # Fallback to manual binning for robustness
            min_r, max_r = min(returns), max(returns)
            if max_r == min_r: return 0
            bin_width = (max_r - min_r) / bins
            counts = [0] * bins
            for r in returns:
                idx = min(int((r - min_r) / bin_width), bins - 1)
                counts[idx] += 1
            
            probs = [c / len(returns) for c in counts if c > 0]
            return -sum(p * math.log(p, 2) for p in probs)
        except:
            return 2.0

    def _get_kurtosis(self, prices):
        if len(prices) < 30: return 0
        n = len(prices)
        mu = statistics.mean(prices)
        std = statistics.stdev(prices)
        if std == 0: return 0
        fourth_moment = sum((x - mu)**4 for x in prices) / n
        return fourth_moment / (std**4)

    def _get_robust_z(self, prices):
        med = statistics.median(prices)
        mad = statistics.median([abs(x - med) for x in prices])
        if mad == 0: return 0
        return (prices[-1] - med) / (mad * 1.4826)

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        current_symbols = list(prices.keys())
        
        for symbol in current_symbols:
            p = prices[symbol].get("priceUsd", 0)
            if p <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["lookback"])
            self.history[symbol].append(p)
            self.last_prices[symbol] = p

        # 1. Exit Logic: Variance Stabilization & Information Entropy Shifts
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.last_prices: continue
            
            hist = list(self.history[symbol])
            if len(hist) < 20: continue
            
            curr_p = self.last_prices[symbol]
            entry_p = self.entry_prices[symbol]
            pnl = (curr_p - entry_p) / entry_p
            
            entropy = self._calculate_shannon_entropy(hist)
            kurt = self._get_kurtosis(hist)
            
            # Exit if the system transitions into high-entropy (random) state
            if entropy > self.params["entropy_threshold"] and pnl > 0.005:
                amount = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["VOLATILITY_ABSORPTION"]}

            # Probability-based threshold exit (non-linear stop logic)
            if pnl < -0.04 or pnl > 0.08:
                amount = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["PROBABILITY_THRESHOLD_REACHED"]}

            # Exit if fat-tail dissipates (kurtosis normalization)
            if kurt < 2.5 and pnl > 0.01:
                amount = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["KURTOSIS_NORMALIZATION"]}

        # 2. Entry Logic: Entropy Collapse & Fat-Tail Reversion
        if len(self.current_positions) < self.max_positions:
            candidates = []
            for symbol in current_symbols:
                if symbol in self.current_positions: continue
                hist = list(self.history.get(symbol, []))
                if len(hist) < self.min_history: continue
                
                robust_z = self._get_robust_z(hist)
                entropy = self._calculate_shannon_entropy(hist)
                kurt = self._get_kurtosis(hist)
                
                # Logic: Extremely high kurtosis (fat tail event) + Extreme robust Z-score
                # + Entropy collapse (signal clarity in the noise)
                if robust_z < -self.params["z_score_cutoff"]:
                    if kurt > self.params["kurtosis_floor"] and entropy < 1.9:
                        candidates.append((abs(robust_z), symbol))

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                target_symbol = candidates[0][1]
                
                price = self.last_prices[target_symbol]
                qty = (self.base_balance * self.params["risk_cap"]) / price
                
                self.current_positions[target_symbol] = qty
                self.entry_prices[target_symbol] = price
                
                return {
                    "side": "BUY",
                    "symbol": target_symbol,
                    "amount": round(qty, 4),
                    "reason": ["FAT_TAIL_REVERSION", "ENTROPY_COLLAPSE"]
                }

        return None

    def on_trade_executed(self, symbol, side, amount, price):
        if side.upper() == "BUY":
            self.current_positions[symbol] = amount
            self.entry_prices[symbol] = price
        else:
            self.current_positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)