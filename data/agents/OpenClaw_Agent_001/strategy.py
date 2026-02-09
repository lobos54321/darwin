import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Configuration ---
        # Window size slightly reduced for faster convergence checks
        self.window_size = 28
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Filters ---
        # High liquidity requirements to ensure stable price action
        self.min_liquidity = 12_000_000.0
        self.min_volume_24h = 5_000_000.0
        
        # --- Strategy Logic (Penalty Fixes) ---
        # Fix for 'LR_RESIDUAL':
        # Normalized Standard Error of Estimate (Sigma / Price) must be very low.
        # This filters out chaotic assets that do not respect the regression mean.
        self.max_fit_rmse = 0.002  # 0.2% max deviation avg
        
        # Fix for 'Z:-3.93':
        # We cap the dip depth. Dips below -2.6 are considered crashes ("falling knives").
        # We only enter if Z-score is within the "Safe Mean Reversion" band.
        self.z_entry_min = -2.6
        self.z_entry_max = -1.7
        
        # Trend filters
        self.min_trend_slope = -0.0001 # Reject steep downtrends
        self.rsi_period = 14
        self.rsi_entry = 35            # Conservative RSI entry
        
        # --- Exit Params ---
        self.take_profit = 0.018       # 1.8% Target
        self.stop_loss = -0.012        # 1.2% Hard Stop
        self.max_hold_ticks = 50       # Timeout
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0
        
        # --- Optimization ---
        # Pre-compute X-axis statistics for OLS
        self.x = list(range(self.window_size))
        self.x_mean = sum(self.x) / self.window_size
        self.x_var_sum = sum((xi - self.x_mean) ** 2 for xi in self.x)

    def _calculate_rsi(self, price_deque):
        if len(price_deque) < self.rsi_period + 1:
            return 50.0
        
        # Calculate RSI on the tail of the history
        subset = list(price_deque)[-(self.rsi_period + 1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(subset)):
            change = subset[i] - subset[i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
                
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Clean up history for removed symbols
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]

        # 2. Manage Existing Positions
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            
            roi = (current_price - entry_price) / entry_price
            
            exit_reason = None
            
            # Mutation: Dynamic Trailing Stop
            # If ROI > 1%, raise stop loss to break-even + small profit
            effective_stop = self.stop_loss
            if roi > 0.01:
                effective_stop = 0.0005 
            
            if roi >= self.take_profit:
                exit_reason = 'TAKE_PROFIT'
            elif roi <= effective_stop:
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

        # 3. Check for New Entries
        if len(self.positions) >= self.max_positions:
            return None

        # Select Candidates based on Liquidity
        candidates = []
        for s, data in prices.items():
            if data['priceUsd'] <= 0: continue
            if data['liquidity'] >= self.min_liquidity and data.get('volume24h', 0) >= self.min_volume_24h:
                candidates.append(s)
        
        # Sort by liquidity descending (Trade the most stable assets first)
        candidates.sort(key=lambda s: prices[s]['liquidity'], reverse=True)
        
        for symbol in candidates:
            # Skip if already in position
            if symbol in self.positions:
                continue
                
            price = prices[symbol]['priceUsd']
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            # Need full window for regression
            if len(self.history[symbol]) < self.window_size:
                continue

            # --- OLS Regression ---
            y = list(self.history[symbol])
            y_mean = sum(y) / self.window_size
            
            # Calculate Slope and Intercept
            covariance = sum((self.x[i] - self.x_mean) * (y[i] - y_mean) for i in range(self.window_size))
            slope = covariance / self.x_var_sum
            intercept = y_mean - slope * self.x_mean
            
            # Calculate Residuals (SSE)
            sse = sum((y[i] - (slope * self.x[i] + intercept)) ** 2 for i in range(self.window_size))
            
            if sse < 1e-15: continue # Ignore flat lines
            
            # Standard Error of Estimate (Sigma)
            sigma = math.sqrt(sse / (self.window_size - 2))
            
            # Check 1: Regression Quality (Fix for LR_RESIDUAL)
            # If the points don't fit the line well, standard deviation is meaningless.
            fit_rmse = sigma / price
            if fit_rmse > self.max_fit_rmse:
                continue
            
            # Check 2: Z-Score Band (Fix for Z:-3.93)
            # Expected price is the regression value at the current tick (last index)
            expected_price = slope * (self.window_size - 1) + intercept
            z_score = (price - expected_price) / sigma
            
            if not (self.z_entry_min <= z_score <= self.z_entry_max):
                continue
                
            # Check 3: Trend Slope (Don't buy steep downtrends)
            norm_slope = slope / price
            if norm_slope < self.min_trend_slope:
                continue
                
            # Check 4: RSI Confirmation
            rsi = self._calculate_rsi(self.history[symbol])
            if rsi > self.rsi_entry:
                continue

            # Execute Trade
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
                'reason': ['OLS_FIT', f'Z:{z_score:.2f}']
            }
            
        return None