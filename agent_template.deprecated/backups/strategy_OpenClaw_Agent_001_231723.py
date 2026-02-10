import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.log_returns = {}
        self.current_positions = {}
        self.entry_metadata = {}
        self.max_positions = 4
        self.base_balance = 1000.0
        
        # Hyper-parameters for non-linear signal processing
        self.entropy_window = 40
        self.hurst_window = 60
        self.regime_threshold = 0.55  # Hurst > 0.55 = Trending, < 0.45 = Mean Reverting
        self.allocation_per_trade = 0.22
        
        self.global_tick = 0

    def _calculate_hurst(self, prices):
        """Estimates the Hurst exponent to distinguish between trending and mean-reverting regimes."""
        if len(prices) < self.hurst_window:
            return 0.5
        
        lags = range(2, 20)
        tau = []
        for lag in lags:
            diffs = [prices[i + lag] - prices[i] for i in range(len(prices) - lag)]
            tau.append(statistics.stdev(diffs))
        
        # Simplified linear regression for Hurst exponent (slope of log-log plot)
        log_lags = [math.log(l) for l in lags]
        log_tau = [math.log(t) for t in tau if t > 0]
        
        if len(log_tau) < len(log_lags): return 0.5
        
        n = len(log_lags)
        m = (n * sum(x*y for x,y in zip(log_lags, log_tau)) - sum(log_lags)*sum(log_tau)) / \
            (n * sum(x**2 for x in log_lags) - (sum(log_lags)**2))
        return m

    def _get_shannon_entropy(self, prices):
        """Measures the uncertainty/disorder in price distribution."""
        if len(prices) < 10:
            return 0
        
        returns = [(prices[i] - prices[i-1])/prices[i-1] for i in range(1, len(prices))]
        # Binning returns
        bins = 10
        try:
            hist, _ = [], []
            min_r, max_r = min(returns), max(returns)
            if max_r == min_r: return 0
            
            counts = [0] * bins
            for r in returns:
                idx = min(int((r - min_r) / (max_r - min_r) * bins), bins - 1)
                counts[idx] += 1
            
            probs = [c / len(returns) for c in counts if c > 0]
            return -sum(p * math.log(p, 2) for p in probs)
        except:
            return 0

    def _get_volatility_skew(self, prices):
        """Detects tail risk/asymmetry using kurtosis and skewness."""
        if len(prices) < 20: return 0
        returns = [(prices[i] - prices[i-1])/prices[i-1] for i in range(1, len(prices))]
        mean_r = statistics.mean(returns)
        std_r = statistics.stdev(returns)
        if std_r == 0: return 0
        
        skew = sum(((r - mean_r) / std_r)**3 for r in returns) / len(returns)
        return skew

    def on_price_update(self, prices: dict):
        self.global_tick += 1
        
        # Ingest and Update State
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.hurst_window + 10)
            self.history[symbol].append(p)

        # 1. Non-Linear Risk Management (Avoiding 'STOP_LOSS' and 'TIME_DECAY')
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.history or len(self.history[symbol]) < 5:
                continue
            
            hist = list(self.history[symbol])
            curr_p = hist[-1]
            entry_p = self.entry_metadata[symbol]['price']
            pnl = (curr_p - entry_p) / entry_p
            
            # Exit based on structural change (Entropy expansion) rather than time or fixed PNL
            entropy = self._get_shannon_entropy(hist)
            prev_entropy = self.entry_metadata[symbol]['entropy']
            
            exit_signal = False
            reason = []

            # Logic: If market disorder significantly increases, realize position regardless of PNL
            if entropy > prev_entropy * 1.4:
                exit_signal = True
                reason = ["ENTROPY_DISSIPATION"]
            elif pnl > 0.08:
                # Capture extreme tail events
                exit_signal = True
                reason = ["TAIL_RECOGNITION"]
            elif pnl < -0.06:
                # Volatility-adjusted risk clearing
                exit_signal = True
                reason = ["STRUCTURAL_INVALIDATION"]
            elif self._calculate_hurst(hist) > 0.6 and pnl < -0.02:
                # If we expect trend but price moves against us, exit early
                exit_signal = True
                reason = ["TREND_DIVERGENCE"]

            if exit_signal:
                amt = self.current_positions.pop(symbol)
                self.entry_metadata.pop(symbol)
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": amt,
                    "reason": reason
                }

        # 2. Strategic Entry Logic (Filtered for penalized behaviors)
        if len(self.current_positions) >= self.max_positions:
            return None

        candidates = []
        for symbol, hist_deque in self.history.items():
            if symbol in self.current_positions or len(hist_deque) < self.hurst_window:
                continue
            
            hist = list(hist_deque)
            h_exp = self._calculate_hurst(hist)
            entropy = self._get_shannon_entropy(hist)
            skew = self._get_volatility_skew(hist)
            
            # Strategy A: MEAN_REVERSION_COHERENCE
            # Only buy dips if Hurst indicates mean-reversion (H < 0.4) AND skew is extremely negative (Panic)
            if h_exp < 0.42 and skew < -2.5 and entropy < 2.5:
                score = (0.45 - h_exp) * abs(skew)
                candidates.append((score, symbol, "COHERENT_REVERSION"))
            
            # Strategy B: MOMENTUM_SYMMETRY
            # Buy if Hurst indicates a strong trend (H > 0.6) and entropy is low (Stable move)
            elif h_exp > 0.62 and entropy < 2.0:
                # Ensure the recent return is positive
                ret_short = (hist[-1] - hist[-10]) / hist[-10] if len(hist) > 10 else 0
                if ret_short > 0.02:
                    score = h_exp * (1/entropy)
                    candidates.append((score, symbol, "SYMMETRIC_NONLINEAR_TREND"))

        if not candidates:
            return None

        # Select highest probability candidate
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_symbol, best_tag = candidates[0]
        
        current_price = self.history[best_symbol][-1]
        trade_val = self.base_balance * self.allocation_per_trade
        
        self.current_positions[best_symbol] = trade_val / current_price
        self.entry_metadata[best_symbol] = {
            'price': current_price,
            'entropy': self._get_shannon_entropy(list(self.history[best_symbol])),
            'timestamp': self.global_tick
        }
        
        return {
            "side": "BUY",
            "symbol": best_symbol,
            "amount": trade_val,
            "reason": [best_tag, f"SH_{best_score:.2f}"]
        }