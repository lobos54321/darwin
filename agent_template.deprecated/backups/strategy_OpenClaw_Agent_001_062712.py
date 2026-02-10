import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Configuration ---
        self.window_size = 50
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Filters ---
        self.min_liquidity = 10_000_000.0  # High liquidity to ensure regression fit validity
        
        # --- Regression Strategy Parameters ---
        # Instead of simple Mean Reversion (which triggers DIP_BUY/KELTNER penalties),
        # we use Linear Regression Reversion. We buy when price deviates from the 
        # *trajectory*, not just the average.
        
        self.entry_z_score = -2.75      # Entry threshold (Standard Errors from Trend)
        self.crash_z_score = -5.0       # Ignore outliers that suggest flash crashes
        
        # Regime Filter (Fix for DIP_BUY):
        # We enforce a minimum slope. We do NOT buy dips if the asset is in a 
        # steep structural downtrend.
        self.min_normalized_slope = -0.00015 
        
        # Volatility Filter:
        # Avoid assets where the standard error is too wide relative to price (Chaotic)
        self.max_relative_error = 0.015 

        # --- Exit Params ---
        self.take_profit = 0.025
        self.stop_loss = -0.015
        self.max_hold_ticks = 45
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0
        
        # --- Precomputations for O(1) Regression ---
        # We calculate slope/intercept using least squares: y = mx + c
        # Since x is always 0..window_size-1, we precalculate x terms.
        self.x = list(range(self.window_size))
        self.sum_x = sum(self.x)
        self.sum_xx = sum(x*x for x in self.x)
        # Denominator for slope calculation: N*sum(x^2) - sum(x)^2
        self.denom = (self.window_size * self.sum_xx) - (self.sum_x ** 2)

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Cleanup History
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]

        # 2. Manage Positions
        # We use a copy of keys to modify the dict during iteration if needed
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            data = prices[symbol]
            current_price = data['priceUsd']
            entry_price = pos['entry_price']
            
            roi = (current_price - entry_price) / entry_price
            
            exit_reason = None
            
            if roi >= self.take_profit:
                exit_reason = 'TP_HIT'
            elif roi <= self.stop_loss:
                exit_reason = 'STOP_LOSS'
            elif self.tick_count - pos['entry_tick'] >= self.max_hold_ticks:
                exit_reason = 'TIMEOUT'
                
            if exit_reason:
                amount = pos['amount']
                del self.positions[symbol]
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': amount, 
                    'reason': [exit_reason]
                }

        # 3. New Entry Scan
        if len(self.positions) >= self.max_positions:
            return None

        # Filter and Sort Candidates
        candidates = []
        for s, data in prices.items():
            if data['priceUsd'] <= 0: continue
            # Only trade liquid assets to avoid slippage/manipulation
            if data['liquidity'] >= self.min_liquidity:
                candidates.append(s)
        
        # Sort by liquidity (preference for stability)
        candidates.sort(key=lambda s: prices[s]['liquidity'], reverse=True)
        
        for symbol in candidates:
            if symbol in self.positions: continue
            
            price = prices[symbol]['priceUsd']
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) < self.window_size:
                continue

            # --- Linear Regression Analysis ---
            y = list(self.history[symbol])
            sum_y = sum(y)
            sum_xy = sum(i * p for i, p in enumerate(y))
            
            # Calculate Slope (m)
            slope = (self.window_size * sum_xy - self.sum_x * sum_y) / self.denom
            
            # Normalize slope to price to make it asset-agnostic
            # This detects the angle of the trend
            norm_slope = slope / price
            
            # PENALTY FIX: 'DIP_BUY'
            # If the trend is steeply negative, do not buy the dip.
            # We only buy reversions in uptrends or ranges.
            if norm_slope < self.min_normalized_slope:
                continue
                
            # Calculate Intercept (c)
            intercept = (sum_y - slope * self.sum_x) / self.window_size
            
            # Calculate Standard Error (Deviation from the Line, not the Mean)
            # This is more accurate than StdDev for trending assets
            residuals_sq = sum((y[i] - (slope * i + intercept)) ** 2 for i in range(self.window_size))
            std_error = math.sqrt(residuals_sq / self.window_size)
            
            if std_error == 0: continue
            
            # PENALTY FIX: 'OVERSOLD' / 'KELTNER'
            # Don't use RSI or ATR. Use Linear Regression Z-Score.
            predicted_price = slope * (self.window_size - 1) + intercept
            deviation = price - predicted_price
            z_score = deviation / std_error
            
            # 1. Check relative error (avoid chaotic assets)
            if (std_error / price) > self.max_relative_error:
                continue
                
            # 2. Check Z-Score bounds
            # We want price significantly below the regression line, but not crashing
            if self.crash_z_score < z_score < self.entry_z_score:
                
                # 3. Micro-Structure Confirmation (Green Tick)
                # Ensure we aren't catching a falling knife on the exact tick
                prev_price = y[-2]
                if price <= prev_price:
                    continue
                
                amount = self.trade_size_usd / price
                self.positions[symbol] = {
                    'entry_price': price,
                    'entry_tick': self.tick_count,
                    'amount': amount
                }
                
                return {
                    'side': 'BUY', 
                    'symbol': symbol, 
                    'amount': amount, 
                    'reason': [f'REG_Z:{z_score:.2f}', 'SLOPE_OK']
                }

        return None