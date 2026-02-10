import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Configuration ---
        self.window_size = 30
        self.min_liquidity = 15000000.0  # $15M min liquidity
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Risk Management (Penalty Fixes) ---
        # Fix for 'LR_RESIDUAL': Stricter fit quality. 
        # If residual deviation > 0.45% of price, the linear model is invalid (too noisy).
        self.max_fit_error = 0.0045 
        
        # Fix for 'Z:-3.93': Prevent catching falling knives.
        # We clamp the buy zone strictly between -2.6 and -1.6.
        # Z < -2.6 is statistically likely to be a crash, not a dip.
        self.z_entry_floor = -2.6
        self.z_entry_ceiling = -1.6
        
        # Trend Filter: Avoid buying into steep downtrends even if Z-score is low.
        self.min_trend_slope = -0.0002
        
        # RSI Filter: Confluence check
        self.rsi_max = 38
        
        # --- State ---
        self.history = {}
        self.positions = {}  # symbol -> {'entry_price': float, 'entry_tick': int, 'amount': float}
        self.tick_count = 0
        
        # --- OLS Pre-calculations ---
        # Pre-computing X-axis stats to speed up on_price_update
        self.x = list(range(self.window_size))
        self.x_mean = statistics.mean(self.x)
        self.x_var_sum = sum((xi - self.x_mean) ** 2 for xi in self.x)

    def _calculate_metrics(self, price_deque):
        """Calculates regression metrics and RSI efficiently."""
        if len(price_deque) < self.window_size:
            return None
            
        y = list(price_deque)
        y_mean = statistics.mean(y)
        current_price = y[-1]
        
        # 1. Linear Regression (OLS)
        # Slope = Sum((x - x_mean)*(y - y_mean)) / Sum((x - x_mean)^2)
        covariance = sum((self.x[i] - self.x_mean) * (y[i] - y_mean) for i in range(self.window_size))
        slope = covariance / self.x_var_sum
        intercept = y_mean - slope * self.x_mean
        
        # 2. Residual Analysis (Fix for LR_RESIDUAL)
        # Calculate standard deviation of the residuals (errors)
        residuals_sq_sum = 0
        for i in range(self.window_size):
            predicted = slope * i + intercept
            residuals_sq_sum += (y[i] - predicted) ** 2
            
        # Standard Error of the Estimate (Sigma)
        sigma = math.sqrt(residuals_sq_sum / (self.window_size - 2))
        
        if sigma == 0: 
            return None

        # Normalized Fit Error (Volatility of noise relative to price)
        fit_error_pct = sigma / current_price
        
        # 3. Z-Score Calculation
        # Expected price is the end of the regression line
        expected_price = slope * (self.window_size - 1) + intercept
        z_score = (current_price - expected_price) / sigma
        
        # 4. RSI (Relative Strength Index) - 14 period
        rsi = 50.0
        rsi_period = 14
        if len(y) > rsi_period:
            # Slicing the last 15 prices to get 14 changes
            recent = y[-(rsi_period+1):]
            gains = 0.0
            losses = 0.0
            for i in range(1, len(recent)):
                change = recent[i] - recent[i-1]
                if change > 0:
                    gains += change
                else:
                    losses += abs(change)
            
            if gains + losses > 0:
                avg_gain = gains / rsi_period
                avg_loss = losses / rsi_period
                if avg_loss == 0:
                    rsi = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100.0 - (100.0 / (1.0 + rs))

        return {
            'z_score': z_score,
            'slope_pct': slope / current_price,
            'fit_error': fit_error_pct,
            'rsi': rsi,
            'price': current_price
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # --- 1. Cleanup Old History ---
        # Remove symbols that are no longer in the feed to save memory
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]

        # --- 2. Exit Logic (Take Profit / Stop Loss) ---
        # Check existing positions first to free up slots/capital
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            amount = pos['amount']
            
            roi = (current_price - entry_price) / entry_price
            
            # Strict stop loss to prevent large drawdowns
            if roi < -0.025: # -2.5% Stop Loss
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['STOP_LOSS']}
            
            # Take Profit - slightly lower to ensure realization
            if roi > 0.012: # +1.2% Take Profit
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TAKE_PROFIT']}
            
            # Time-based exit (Rotting position)
            if self.tick_count - pos['entry_tick'] > 80:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TIMEOUT']}

        # --- 3. Entry Logic ---
        if len(self.positions) >= self.max_positions:
            return None

        # Sort candidates by liquidity to prioritize stable assets
        # We process a few top liquid assets to find the best setup
        candidates = []
        for s, data in prices.items():
            if data['liquidity'] < self.min_liquidity:
                continue
            candidates.append(s)
            
        # Update history and check signals
        for symbol in candidates:
            price = prices[symbol]['priceUsd']
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) < self.window_size:
                continue
                
            # Don't buy if we already hold it
            if symbol in self.positions:
                continue

            metrics = self._calculate_metrics(self.history[symbol])
            if not metrics:
                continue
                
            # --- SIGNAL FILTERS ---
            
            # 1. Fit Quality (LR_RESIDUAL Fix)
            # If the price is too noisy around the regression line, Z-score is unreliable.
            if metrics['fit_error'] > self.max_fit_error:
                continue
                
            # 2. Z-Score "Sweet Spot" (Z:-3.93 Fix)
            # Must be a dip, but not a crash.
            if not (self.z_entry_floor <= metrics['z_score'] <= self.z_entry_ceiling):
                continue
                
            # 3. Slope Check
            # Ensure we aren't catching a knife in a severe downtrend
            if metrics['slope_pct'] < self.min_trend_slope:
                continue
                
            # 4. RSI Confluence
            if metrics['rsi'] > self.rsi_max:
                continue
                
            # 5. Daily Trend Check (Mutation)
            # Avoid buying assets that are already down massively today (potential rug/exploit)
            if prices[symbol]['priceChange24h'] < -10.0:
                continue
            
            # --- EXECUTE BUY ---
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
                'reason': ['LR_MEAN_REV', f'Z:{metrics["z_score"]:.2f}']
            }
            
        return None