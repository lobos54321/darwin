import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Configuration ---
        # Mutation: Reduced window size slightly to be more reactive to recent shifts
        self.window_size = 30
        
        # Mutation: High liquidity/volume filters to ensure market depth
        self.min_liquidity = 15_000_000.0
        self.min_volume_24h = 8_000_000.0
        
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Penalty Fixes ---
        # Fix for 'LR_RESIDUAL': Very strict fit error threshold (0.25%).
        # This rejects assets where the regression line is a poor predictor (high noise).
        self.max_fit_error = 0.0025 
        
        # Fix for 'Z:-3.93': Conservative Mean Reversion Band.
        # We reject Z-scores below -2.5 (too risky/crashing) and above -1.8 (not enough profit).
        self.z_entry_min = -2.5
        self.z_entry_max = -1.8
        
        # --- Filters ---
        self.min_trend_slope = -0.00015 # Allow slight downtrend, but not steep
        self.rsi_period = 14
        self.rsi_max = 32               # Slightly loosened from 30 to allow entry in strong trends
        self.max_daily_drop = -0.07     # Avoid assets down > 7% in 24h
        
        # --- Exit Params ---
        self.take_profit = 0.015        # +1.5%
        self.stop_loss = -0.015         # -1.5%
        self.max_hold_ticks = 45        # Close after ~45 ticks if no result
        
        # --- State ---
        self.history = {}     # symbol -> deque of prices
        self.positions = {}   # symbol -> position dict
        self.tick_count = 0
        
        # --- Optimization ---
        # Pre-compute X-axis statistics for OLS (0, 1, ..., window_size-1)
        self.x = list(range(self.window_size))
        self.x_mean = sum(self.x) / len(self.x)
        self.x_var_sum = sum((xi - self.x_mean) ** 2 for xi in self.x)

    def _calculate_rsi(self, price_deque):
        """Calculates RSI on the last 15 prices."""
        if len(price_deque) < self.rsi_period + 1:
            return 50.0
            
        changes = []
        # Look at the tail of the deque
        # We need rsi_period changes, so we need rsi_period + 1 prices
        snapshot = list(price_deque)[-(self.rsi_period + 1):]
        
        for i in range(1, len(snapshot)):
            changes.append(snapshot[i] - snapshot[i-1])
            
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c < 0)
        
        if losses == 0:
            return 100.0
        if gains == 0:
            return 0.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Clean up stale history
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]

        # 2. Manage Existing Positions
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            amount = pos['amount']
            
            # ROI Calculation
            roi = (current_price - entry_price) / entry_price
            
            # Exit Conditions
            exit_reason = None
            if roi >= self.take_profit:
                exit_reason = 'TAKE_PROFIT'
            elif roi <= self.stop_loss:
                exit_reason = 'STOP_LOSS'
            elif self.tick_count - pos['entry_tick'] >= self.max_hold_ticks:
                exit_reason = 'TIMEOUT'
                
            if exit_reason:
                del self.positions[symbol]
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': amount, 
                    'reason': [exit_reason]
                }

        # 3. Check Entry Conditions
        if len(self.positions) >= self.max_positions:
            return None

        # Filter and Sort Candidates by Liquidity (Safety first)
        candidates = []
        for s, data in prices.items():
            # Basic data integrity check
            if data['priceUsd'] <= 0: continue
            
            if data['liquidity'] >= self.min_liquidity and data.get('volume24h', 0) >= self.min_volume_24h:
                candidates.append(s)
        
        # Sort by liquidity descending to prioritize most liquid pairs
        candidates.sort(key=lambda s: prices[s]['liquidity'], reverse=True)
        
        for symbol in candidates:
            # Skip if already in position
            if symbol in self.positions:
                continue
                
            price = prices[symbol]['priceUsd']
            
            # Update Price History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            # Require full window for regression
            if len(self.history[symbol]) < self.window_size:
                continue

            # --- OLS Regression ---
            y = list(self.history[symbol])
            y_mean = sum(y) / len(y)
            
            # Covariance (sum((x-mean)*(y-mean)))
            covariance = sum((self.x[i] - self.x_mean) * (y[i] - y_mean) for i in range(self.window_size))
            
            slope = covariance / self.x_var_sum
            intercept = y_mean - slope * self.x_mean
            
            # Calculate Sum of Squared Errors (SSE)
            sse = 0.0
            for i in range(self.window_size):
                pred = slope * self.x[i] + intercept
                sse += (y[i] - pred) ** 2
            
            if sse < 1e-12: continue # Avoid div by zero on flat lines
            
            # Standard Error of Estimate (Sigma)
            sigma = math.sqrt(sse / (self.window_size - 2))
            
            # Normalized Fit Error (Risk Metric)
            fit_error = sigma / price
            
            # --- Checks ---
            
            # 1. LR_RESIDUAL Fix: Model fit quality
            if fit_error > self.max_fit_error:
                continue
            
            # Calculate Z-Score of current price
            # Expected price is the projection at the last index
            expected_price = slope * (self.window_size - 1) + intercept
            z_score = (price - expected_price) / sigma
            
            # 2. Z:-3.93 Fix: Strict Band [-2.5, -1.8]
            if not (self.z_entry_min <= z_score <= self.z_entry_max):
                continue
                
            # 3. Slope check (Avoid catching falling knives on steep slopes)
            norm_slope = slope / price
            if norm_slope < self.min_trend_slope:
                continue
                
            # 4. Crash Protection (24h change)
            if prices[symbol]['priceChange24h'] < self.max_daily_drop:
                continue
                
            # 5. RSI Check (Secondary oversold confirmation)
            rsi = self._calculate_rsi(self.history[symbol])
            if rsi > self.rsi_max:
                continue

            # --- Execute Trade ---
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
                'reason': ['OLS_FIT', f'Z:{z_score:.2f}', f'ERR:{fit_error:.4f}']
            }
            
        return None