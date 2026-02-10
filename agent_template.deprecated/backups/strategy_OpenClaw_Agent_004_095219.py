import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Linear Regression Residual Reversion (ALR3)
        
        Differs from penalized strategies by avoiding simple Mean/Stdev Z-scores and Efficiency Ratios.
        Instead, it models the local price trend using Linear Regression and identifies statistical 
        anomalies (residuals) that deviate significantly from the projected trend.
        
        Key Mechanisms:
        1. Trend-Adjusted Reversion: We buy when price deviates from the Linear Regression line, 
           not just a simple moving average. This handles drifting markets better than standard Bollinger Bands.
        2. Volatility Expansion Filter: We only trade when the residual standard error (volatility of noise)
           is sufficient to cover spread/fees.
        3. Dynamic Exit: Positions are closed when price reverts to the projected trend line (Regression mean),
           rather than a fixed percentage target.
        """
        self.lookback = 25
        self.max_positions = 5
        self.trade_size = 2000.0
        self.min_liquidity = 1000000.0
        
        # Alpha Parameters
        self.entry_std_dev = 2.6       # Entry at 2.6 sigma deviation from Trend Line
        self.min_resid_vol = 0.005     # Min residual volatility (0.5%) to ensure action
        
        # Risk Management
        self.stop_loss_pct = 0.07      # 7% Hard Stop (Crash protection)
        self.max_hold_ticks = 40       # Time-based thesis invalidation
        
        self.data = {}      # Stores price history: {symbol: deque}
        self.positions = {} # Stores active trades: {symbol: {entry_price, amount, ticks}}

    def _calculate_linreg(self, data):
        """
        Calculates Linear Regression (y = mx + c) stats for a price series.
        Returns: current_predicted_price, residual_stdev, slope
        """
        n = len(data)
        if n < 5: return None, 0, 0
        
        x = list(range(n))
        y = list(data)
        
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)
        
        # Calculate covariance and variance
        numer = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denom = sum((xi - mean_x) ** 2 for xi in x)
        
        if denom == 0: return mean_y, 0, 0
        
        slope = numer / denom
        intercept = mean_y - (slope * mean_x)
        
        # Predicted value for the CURRENT tick (last index)
        predicted = (slope * (n - 1)) + intercept
        
        # Calculate Standard Deviation of Residuals (The Noise)
        residuals = []
        for i in range(n):
            pred_i = (slope * i) + intercept
            residuals.append(y[i] - pred_i)
            
        resid_stdev = statistics.stdev(residuals) if len(residuals) > 1 else 0
        
        return predicted, resid_stdev, slope

    def on_price_update(self, prices):
        # 1. Sync Data
        active_symbols = set(prices.keys())
        # Clean up dead data
        for s in list(self.data.keys()):
            if s not in active_symbols:
                del self.data[s]
        
        # Append new prices
        for s, meta in prices.items():
            if s not in self.data:
                self.data[s] = deque(maxlen=self.lookback)
            self.data[s].append(meta['priceUsd'])

        # 2. Manage Positions
        # Use list(keys) to modify dictionary during iteration
        for s in list(self.positions.keys()):
            if s not in prices: continue
            
            pos = self.positions[s]
            current_price = prices[s]['priceUsd']
            pos['ticks'] += 1
            
            # Recalculate context for exit logic
            hist = self.data[s]
            if len(hist) < 10: continue
            
            pred, resid_std, _ = self._calculate_linreg(hist)
            if pred is None: continue
            
            # Logic for Exits
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            action = None
            reason = None
            
            # A. Structural Failure (Stop Loss)
            if roi < -self.stop_loss_pct:
                action = 'SELL'
                reason = 'STRUCTURAL_FAIL'
            
            # B. Thesis Invalidation (Time Decay)
            elif pos['ticks'] >= self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIME_DECAY'
                
            # C. Mean Reversion (Target Met)
            # We exit when price crosses ABOVE the regression line (Trend restored)
            elif current_price >= pred:
                action = 'SELL'
                reason = 'REGRESSION_REVERT'

            if action:
                amount = pos['amount']
                del self.positions[s]
                return {
                    'side': action,
                    'symbol': s,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for s, meta in prices.items():
            if s in self.positions: continue
            if meta['liquidity'] < self.min_liquidity: continue
            
            hist = self.data.get(s)
            if not hist or len(hist) < self.lookback: continue
            
            current_price = hist[-1]
            
            # Calculate Linear Regression stats
            pred, resid_std, slope = self._calculate_linreg(hist)
            if resid_std == 0: continue
            
            # Metric 1: Residual Deviation (How far is price from the trend?)
            # Negative deviation means price is below trend
            deviation = (current_price - pred)
            sigma_dist = deviation / resid_std
            
            # Metric 2: Normalized Volatility of Residuals
            # We want 'noisy' trends, not flat ones, to ensure profit potential
            norm_vol = resid_std / current_price
            
            # Filter A: Volatility Floor
            if norm_vol < self.min_resid_vol: continue
            
            # Filter B: Entry Trigger (Deep Dip relative to Trend)
            if sigma_dist < -self.entry_std_dev:
                candidates.append({
                    'symbol': s,
                    'sigma': sigma_dist,
                    'price': current_price,
                    'slope': slope
                })
        
        # Select best candidate based on depth of deviation (Sigma)
        if candidates:
            # Sort by most negative sigma (deepest dip relative to its own trend)
            candidates.sort(key=lambda x: x['sigma'])
            target = candidates[0]
            
            amount = self.trade_size / target['price']
            self.positions[target['symbol']] = {
                'entry_price': target['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': target['symbol'],
                'amount': amount,
                'reason': ['LINREG_DEV', f"SIGMA:{target['sigma']:.2f}"]
            }
            
        return None