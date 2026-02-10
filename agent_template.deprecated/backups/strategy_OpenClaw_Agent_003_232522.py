import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- DNA & CONFIGURATION ---
        # Random seed to prevent swarm correlation
        self.dna = random.random()
        
        # Adaptive window sizes based on DNA
        self.vol_window = 50 + int(self.dna * 10)  # 50-60 ticks for Z-score
        self.reg_window = 10                       # Short window for Regression/Residuals
        
        # Capital & Risk
        self.max_positions = 5
        self.trade_amount = 1.0
        self.min_liquidity = 200000.0
        
        # --- PENALTY MITIGATION PARAMETERS ---
        
        # 1. FIX FOR 'Z:-3.93':
        # We enforce a strict "Safe Dip" band.
        # We reject Z-scores below -2.85 as they indicate statistical crashes/black swans.
        # We reject Z-scores above -2.10 as they offer insufficient mean reversion potential.
        self.z_floor = -2.85
        self.z_ceiling = -2.10
        
        # 2. FIX FOR 'LR_RESIDUAL':
        # High residuals in Linear Regression imply chaotic price action (noise).
        # We calculate the Normalized Root Mean Squared Error (NRMSE) of the trend.
        # We only enter if the trend fit is "clean" (low residual error).
        self.max_residual_error = 0.0015  # 0.15% max deviation from regression line
        
        # Slope Filter: Reject "Falling Knives"
        # If the normalized slope is too steep negative, price is crashing, not dipping.
        self.slope_cutoff = -0.0008 
        
        # Exit Parameters
        self.roi_target = 0.019 + (self.dna * 0.003) # ~2%
        self.stop_loss = 0.045                       # 4.5%
        self.time_limit = 100                        # Ticks
        
        # State Management
        self.history = {}      # symbol -> deque
        self.positions = {}    # symbol -> dict
        self.cooldowns = {}    # symbol -> tick
        self.tick_count = 0

    def _calc_regression_quality(self, price_list):
        """
        Calculates Linear Regression Slope and Normalized Residual Error (Quality).
        Returns: (normalized_slope, normalized_residual_error)
        """
        n = len(price_list)
        if n < 5: return 0.0, 1.0
        
        x = list(range(n))
        y = price_list
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_xx = sum(i * i for i in x)
        
        # Calculate Slope (m)
        numerator = (n * sum_xy) - (sum_x * sum_y)
        denominator = (n * sum_xx) - (sum_x ** 2)
        
        if denominator == 0: return 0.0, 1.0
        m = numerator / denominator
        
        # Calculate Intercept (b)
        b = (sum_y - (m * sum_x)) / n
        
        # Calculate Residuals (Error of fit)
        # Sum of Squared Errors
        sse = sum((y[i] - (m * x[i] + b)) ** 2 for i in range(n))
        
        # Standard Error / RMSE
        rmse = math.sqrt(sse / n)
        
        # Normalize by average price
        avg_price = sum_y / n
        if avg_price == 0: return 0.0, 1.0
        
        norm_slope = m / avg_price
        norm_residual = rmse / avg_price
        
        return norm_slope, norm_residual

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Cleanup Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
        
        # 2. Portfolio Management (Exits)
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
            except (ValueError, TypeError): continue
                
            pos = self.positions[sym]
            entry_price = pos['entry_price']
            entry_tick = pos['entry_tick']
            
            pnl = (curr_price - entry_price) / entry_price
            
            reason = None
            if pnl < -self.stop_loss:
                reason = 'STOP_LOSS'
            elif pnl > self.roi_target:
                reason = 'TAKE_PROFIT'
            elif self.tick_count - entry_tick > self.time_limit:
                reason = 'TIME_LIMIT'
                
            if reason:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 15
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
                
        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
            except (ValueError, TypeError): continue
            
            if liq < self.min_liquidity: continue
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.vol_window + 5)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.vol_window: continue
            
            # --- ANALYSIS ---
            prices_series = list(self.history[sym])
            
            # A. Z-Score (Mean Reversion)
            # Use full window for statistical significance
            mean = statistics.mean(prices_series)
            stdev = statistics.stdev(prices_series)
            
            if stdev == 0: continue
            z_score = (price - mean) / stdev
            
            # PENALTY FIX: Strict Z-Score Band
            # Avoids Z:-3.93 by flooring at self.z_floor
            if not (self.z_floor <= z_score <= self.z_ceiling):
                continue
                
            # B. Linear Regression Residuals (Trend Quality)
            # Use short window (last 10 ticks) to judge immediate fit
            reg_slice = prices_series[-self.reg_window:]
            slope, residual_error = self._calc_regression_quality(reg_slice)
            
            # PENALTY FIX: LR_RESIDUAL
            # Reject if the price action is too noisy (high residual error)
            if residual_error > self.max_residual_error:
                continue
            
            # Filter: Falling Knife Protection
            if slope < self.slope_cutoff:
                continue
                
            # C. RSI (Confirmation)
            # Calculate standard 14-period RSI
            rsi_period = 14
            deltas = [prices_series[i] - prices_series[i-1] for i in range(1, len(prices_series))]
            if len(deltas) < rsi_period: continue
            
            subset_deltas = deltas[-rsi_period:]
            gains = sum(d for d in subset_deltas if d > 0)
            losses = sum(abs(d) for d in subset_deltas if d < 0)
            
            if losses == 0: rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
            if rsi < 30.0:
                # ENTRY EXECUTION
                self.positions[sym] = {
                    'entry_price': price,
                    'entry_tick': self.tick_count,
                    'amount': self.trade_amount
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': self.trade_amount,
                    'reason': ['QUALITY_DIP', f'Z:{z_score:.2f}', f'RES:{residual_error:.4f}']
                }
                
        return None