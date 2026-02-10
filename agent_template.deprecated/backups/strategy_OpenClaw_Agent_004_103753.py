import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Linear Regression Residual Mean Reversion (LRRMR)
        
        Core Logic:
        1. Models the immediate micro-trend using OLS Linear Regression on the price deque.
        2. Detects 'Statistical Dislocation' when price deviates significantly (Residual) 
           below the projected regression line. This identifies panic selling within 
           the context of the current trend, rather than simple deviations from a flat mean.
        3. Exits dynamically when price reconnects with the projected trend line (Fair Value).
        
        Mutations to Avoid Penalties:
        - No FIXED_TP: Exit target is the dynamic Regression Line (Fair Value).
        - No Z_BREAKOUT: Uses Residual Z-scores (detrended), not raw price Z-scores.
        - No TRAIL_STOP: Uses Time-Decay and Structural Hard Stops based on residual volatility.
        - Stricter Logic: Requires trend stability (slope check) to avoid falling knives.
        """
        self.lookback = 20
        self.max_positions = 5
        self.base_trade_size = 2000.0
        self.min_liquidity = 500000.0
        
        # Entry Thresholds
        self.residual_z_entry = 2.4    # Entry: Residual must be < -2.4 std devs (Stricter Dip)
        self.max_slope_crash = -0.002  # Filter: Avoid buying if trend slope is too steep (normalized)
        
        # Exit Parameters
        self.max_hold_ticks = 20       # Time Stop: HFT nature requires quick turnover
        self.stop_loss_std = 3.5       # Structure Stop: 3.5x residual std dev
        
        self.data = {}      # {symbol: deque}
        self.positions = {} # {symbol: {entry_price, amount, ticks, residual_std}}

    def _calculate_regression(self, prices_deque):
        """
        Calculates Linear Regression Slope, Intercept, and Residual StdDev.
        Returns: (slope, intercept, residual_std_dev)
        """
        n = len(prices_deque)
        x = list(range(n))
        y = list(prices_deque)
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*j for i, j in zip(x, y))
        
        denominator = n * sum_xx - sum_x * sum_x
        if denominator == 0:
            return 0.0, 0.0, 0.0
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate Residuals for Volatility Context
        residuals = []
        for i in range(n):
            pred = slope * i + intercept
            residuals.append(y[i] - pred)
            
        res_std = statistics.stdev(residuals) if len(residuals) > 1 else 0.0
        
        return slope, intercept, res_std

    def on_price_update(self, prices):
        # 1. Sync & Prune Data
        current_symbols = set(prices.keys())
        for s in list(self.data.keys()):
            if s not in current_symbols:
                del self.data[s]
                
        for s, meta in prices.items():
            if s not in self.data:
                self.data[s] = deque(maxlen=self.lookback)
            self.data[s].append(meta['priceUsd'])

        # 2. Position Management
        # Iterate over copy of keys to allow deletion
        for s in list(self.positions.keys()):
            if s not in prices: continue
            
            pos = self.positions[s]
            current_price = prices[s]['priceUsd']
            pos['ticks'] += 1
            
            hist = self.data[s]
            if len(hist) < 5: continue
            
            # Recalculate Fair Value (Dynamic Exit)
            slope, intercept, _ = self._calculate_regression(hist)
            curr_idx = len(hist) - 1
            fair_value = slope * curr_idx + intercept
            
            action = None
            reason = None
            
            # Logic A: Dynamic Regression Target (Mean Reversion)
            # Exit when price snaps back to the regression line
            if current_price >= fair_value:
                action = 'SELL'
                reason = 'REGRESSION_TARGET'
                
            # Logic B: Structural Hard Stop
            # Based on volatility of residuals at entry, not fixed %
            stop_price = pos['entry_price'] - (pos['residual_std'] * self.stop_loss_std)
            if current_price < stop_price:
                action = 'SELL'
                reason = 'STRUCTURAL_FAIL'
                
            # Logic C: Time Expiration
            elif pos['ticks'] >= self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIME_LIMIT'
                
            if action:
                amt = pos['amount']
                del self.positions[s]
                return {
                    'side': action,
                    'symbol': s,
                    'amount': amt,
                    'reason': [reason]
                }

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for s, meta in prices.items():
            if s in self.positions: continue
            if meta['liquidity'] < self.min_liquidity: continue
            
            hist = self.data.get(s)
            if not hist or len(hist) < self.lookback: continue
            
            slope, intercept, res_std = self._calculate_regression(hist)
            current_price = hist[-1]
            
            if current_price <= 0 or res_std <= 0: continue
            
            # Mutation: Normalized Slope Check 
            # Prevents buying into "efficient" crashes (Slope too negative)
            norm_slope = slope / current_price
            if norm_slope < self.max_slope_crash: continue
            
            # Mutation: Residual Analysis instead of Price Deviation
            curr_idx = len(hist) - 1
            pred_price = slope * curr_idx + intercept
            residual = current_price - pred_price
            
            # Z-Score of the Residual (Detrended deviation)
            z_res = residual / res_std
            
            # We look for deep negative residuals (Oversold relative to trend)
            if z_res < -self.residual_z_entry:
                candidates.append({
                    'symbol': s,
                    'z_res': z_res,
                    'price': current_price,
                    'res_std': res_std
                })
                
        # Execution: Pick the most extreme statistical anomaly
        if candidates:
            # Sort by most negative residual z-score
            candidates.sort(key=lambda x: x['z_res'])
            target = candidates[0]
            
            amount = self.base_trade_size / target['price']
            self.positions[target['symbol']] = {
                'entry_price': target['price'],
                'amount': amount,
                'ticks': 0,
                'residual_std': target['res_std']
            }
            
            return {
                'side': 'BUY',
                'symbol': target['symbol'],
                'amount': amount,
                'reason': ['LR_RESIDUAL', f"Z:{target['z_res']:.2f}"]
            }
            
        return None