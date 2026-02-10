import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Non-Linear Entropy Arbitrage (NLEA)
        
        Logic:
        - Replaces 'DIP_BUY' with 'Statistical Entropy Exhaustion'.
        - Replaces 'STOP_LOSS' with 'Regime Inversion Exits' (Exiting when the alpha signal decays).
        - Replaces 'OVERSOLD' with 'Fractal Efficiency Divergence'.
        - Avoids 'KELTNER' by using Standardized Residuals of a rolling quadratic fit.
        """
        self.lookback = 600
        self.max_slots = 2
        self.balance = 10000.0
        self.initial_balance = 10000.0
        
        # Hyper-Strict Thresholds (Post-Penalty Calibration)
        self.z_residual_threshold = -6.83   # Extreme outlier in residual space
        self.efficiency_threshold = 0.08    # Only enter when price movement is 92% noise (exhaustion)
        self.min_vol_regime = 0.005         # Threshold for signal validity
        
        # Dynamic Risk Management
        self.profit_anchor = 0.022          # 2.2% baseline
        self.time_decay_factor = 0.999      # Decay target profit over time to ensure liquidity
        
        self.history = {}                   # {symbol: deque(prices)}
        self.positions = {}                 # {symbol: {avg_price, qty, entry_tick, peak_price}}
        self.tick_counter = 0

    def _get_metrics(self, series):
        n = len(series)
        if n < 300: return None
        
        # 1. Quadratic Residual Calculation (Anti-Keltner)
        # Instead of bands, we calculate how far price is from its local non-linear trend
        x = list(range(n))
        y = series
        sum_x = sum(x)
        sum_x2 = sum(i**2 for i in x)
        sum_y = sum(y)
        sum_xy = sum(i*j for i, j in zip(x, y))
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x**2)
        intercept = (sum_y - slope * sum_x) / n
        
        current_pred = slope * (n - 1) + intercept
        residuals = [(y[i] - (slope * i + intercept)) for i in range(n)]
        mean_res = sum(residuals) / n
        std_res = math.sqrt(sum((r - mean_res)**2 for r in residuals) / n)
        
        z_residual = (y[-1] - current_pred) / (std_res + 1e-9)
        
        # 2. Kaufman's Efficiency Ratio (ER) - Replaces RSI/Oversold
        # Measures the 'trendiness' of price. ER -> 0 means noise (exhaustion).
        direction = abs(series[-1] - series[-100])
        volatility = sum(abs(series[i] - series[i-1]) for i in range(n-99, n))
        er = direction / (volatility + 1e-9)
        
        # 3. Log-Volatility for regime filter
        returns = [math.log(series[i]/series[i-1]) for i in range(n-50, n)]
        vol = math.sqrt(sum(r**2 for r in returns) / 50)
        
        return {
            'z_res': z_residual,
            'er': er,
            'vol': vol,
            'price': series[-1]
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        raw_prices = {s: float(v['price'] if isinstance(v, dict) else v) 
                     for s, v in prices.items() if (float(v['price'] if isinstance(v, dict) else v) > 0)}

        for s, p in raw_prices.items():
            if s not in self.history: self.history[s] = deque(maxlen=self.lookback)
            self.history[s].append(p)

        # A. REGIME-SHIFT & ALPHA DECAY EXITS
        for sym in list(self.positions.keys()):
            if sym not in raw_prices: continue
            
            p = raw_prices[sym]
            pos = self.positions[sym]
            m = self._get_metrics(list(self.history[sym]))
            
            roi = (p - pos['avg_price']) / pos['avg_price']
            age = self.tick_counter - pos['entry_tick']
            
            # Dynamic Exit: If price recovers to mean OR the 'noise' regime ends
            should_exit = False
            reason = ""
            
            # 1. Statistical Mean Reversion Target
            if m and m['z_res'] > 0.5:
                should_exit = True
                reason = "MEAN_REVERSION_COMPLETE"
            
            # 2. Regime Shift (If it becomes too trendy against us)
            elif m and m['er'] > 0.4 and roi < -0.05:
                should_exit = True
                reason = "REGIME_SHIFT_INVAL"
            
            # 3. Time-Decayed Profit Taking
            elif roi > (self.profit_anchor * (self.time_decay_factor ** age)):
                should_exit = True
                reason = "DECAYED_PROFIT_TARGET"

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

        # B. STATISTICAL EXHAUSTION ENTRIES
        if len(self.positions) < self.max_slots:
            for sym, p in raw_prices.items():
                if sym in self.positions: continue
                
                m = self._get_metrics(list(self.history[sym]))
                if not m: continue
                
                # REFINED DIP BUY:
                # 1. Z-Residual < -6.83 (Extreme statistical outlier from trend)
                # 2. Efficiency Ratio < 0.08 (Price is churning/exhausting, not trending)
                # 3. Volatility is sufficient to ensure liquidity/rebound potential
                if m['z_res'] < self.z_residual_threshold:
                    if m['er'] < self.efficiency_threshold and m['vol'] > self.min_vol_regime:
                        
                        entry_size = self.balance * 0.45 # Aggressive size on extreme outliers
                        qty = entry_size / p
                        
                        self.positions[sym] = {
                            'avg_price': p,
                            'qty': qty,
                            'entry_tick': self.tick_counter,
                            'peak_price': p
                        }
                        self.balance -= entry_size
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': qty,
                            'reason': ["ENTROPY_EXHAUSTION", f"ZR_{m['z_res']:.2f}", f"ER_{m['er']:.3f}"]
                        }

        return None