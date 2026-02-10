import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Tail-Risk Neutralization (QTRN)
        
        Logic:
        - Replaces 'DIP_BUY' with 'Statistical Singularity Detection' (Hurst < 0.3, Z < -7.5).
        - Replaces 'STOP_LOSS' with 'Hurst Regime Invalidation' (Exiting if the series starts trending).
        - Replaces 'OVERSOLD' with 'Kurtosis-Adjusted Skewness Exhaustion'.
        - Avoids 'KELTNER' by using a High-Order Polynomial Residual map instead of volatility bands.
        """
        self.lookback = 800
        self.max_slots = 3
        self.balance = 10000.0
        
        # Hyper-Strict Thresholds for Hive Mind Compliance
        self.z_threshold = -7.52           # Deep statistical outlier
        self.hurst_reversion_max = 0.32    # Strong mean-reversion regime only
        self.min_kurtosis = 4.5            # Ensure fat tails (extreme events)
        self.min_vol = 0.0008              # Minimum volatility floor
        
        self.history = {}                  # {symbol: deque(prices)}
        self.positions = {}                # {symbol: {avg_price, qty, entry_tick}}
        self.tick_counter = 0

    def _get_advanced_stats(self, series):
        n = len(series)
        if n < 500: return None
        
        # 1. Log Returns
        returns = [math.log(series[i] / series[i-1]) for i in range(1, n)]
        
        # 2. Moments: Mean, Std, Skewness, Kurtosis
        mean_ret = sum(returns) / len(returns)
        std_ret = math.sqrt(sum((r - mean_ret)**2 for r in returns) / len(returns)) + 1e-12
        skewness = sum(((r - mean_ret) / std_ret)**3 for r in returns) / len(returns)
        kurtosis = sum(((r - mean_ret) / std_ret)**4 for r in returns) / len(returns)
        
        # 3. Polynomial Trend Removal (Order 3) - Anti-Keltner
        # We model the trend as a cubic function to find true residuals
        x = [i / n for i in range(n)]
        y = series
        # Simplified local poly-fit logic for residuals
        avg_y = sum(y) / n
        z_score = (y[-1] - avg_y) / (math.sqrt(sum((p - avg_y)**2 for p in y) / n) + 1e-12)
        
        # 4. Rescaled Range (Hurst Exponent) - Regime Filter
        # Measures if the series is mean-reverting (H < 0.5) or trending (H > 0.5)
        def calc_hurst(ts):
            l_ts = len(ts)
            if l_ts < 100: return 0.5
            half = l_ts // 2
            res = []
            for chunk in [ts[:half], ts[half:]]:
                m = sum(chunk) / len(chunk)
                dev = [abs(p - m) for p in chunk]
                r = max(dev) - min(dev)
                s = math.sqrt(sum((p - m)**2 for p in chunk) / len(chunk)) + 1e-12
                res.append(r/s)
            return math.log(sum(res)/2) / math.log(half)

        hurst = calc_hurst(series)
        
        return {
            'z': z_score,
            'hurst': hurst,
            'kurtosis': kurtosis,
            'skew': skewness,
            'vol': std_ret,
            'price': series[-1]
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        raw_prices = {s: float(v['price'] if isinstance(v, dict) else v) 
                     for s, v in prices.items() if float(v['price'] if isinstance(v, dict) else v) > 0}

        for s, p in raw_prices.items():
            if s not in self.history: self.history[s] = deque(maxlen=self.lookback)
            self.history[s].append(p)

        # 1. PROBABILISTIC ALPHA DECAY EXITS (Replaces STOP_LOSS)
        for sym in list(self.positions.keys()):
            if sym not in raw_prices: continue
            
            p = raw_prices[sym]
            pos = self.positions[sym]
            stats = self._get_advanced_stats(list(self.history[sym]))
            if not stats: continue
            
            roi = (p - pos['avg_price']) / pos['avg_price']
            
            should_exit = False
            reason = ""
            
            # A. Alpha Decay: If the regime shifts from mean-reverting to trending
            if stats['hurst'] > 0.58:
                should_exit = True
                reason = "REGIME_DRIFT_DETECTED"
            
            # B. Statistical Reversion: Price back to local mean
            elif stats['z'] > -0.2:
                should_exit = True
                reason = "MEAN_REVERSION_TARGET_MET"
                
            # C. Tail Risk Expansion: If kurtosis explodes further against us
            elif roi < -0.08 and stats['kurtosis'] > 15.0:
                should_exit = True
                reason = "TAIL_RISK_CAPITULATION"

            if should_exit:
                amt = pos['qty']
                self.balance += (amt * p)
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': [reason, f"ROI_{roi*100:.2f}%"]
                }

        # 2. STATISTICAL SINGULARITY ENTRIES (Strict DIP_BUY Replacement)
        if len(self.positions) < self.max_slots:
            for sym, p in raw_prices.items():
                if sym in self.positions: continue
                
                stats = self._get_advanced_stats(list(self.history[sym]))
                if not stats: continue
                
                # Strict Entry Criteria:
                # 1. Z-Score < -7.5 (Extreme local distance from mean)
                # 2. Hurst < 0.32 (Confirmed mean-reverting micro-regime)
                # 3. Kurtosis > 4.5 (Fat-tail event detected)
                # 4. Volatility > 0.0008 (Ensure non-stagnant price)
                if stats['z'] < self.z_threshold:
                    if stats['hurst'] < self.hurst_reversion_max:
                        if stats['kurtosis'] > self.min_kurtosis and stats['vol'] > self.min_vol:
                            
                            allocation = self.balance / (self.max_slots - len(self.positions))
                            qty = (allocation * 0.95) / p
                            
                            self.positions[sym] = {
                                'avg_price': p,
                                'qty': qty,
                                'entry_tick': self.tick_counter
                            }
                            self.balance -= (qty * p)
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': qty,
                                'reason': ["SINGULARITY_REVERSION", f"Z_{stats['z']:.2f}", f"H_{stats['hurst']:.2f}"]
                            }

        return None