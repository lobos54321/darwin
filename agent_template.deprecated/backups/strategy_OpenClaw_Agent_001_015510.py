import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        self.window_size = 30
        self.min_liquidity = 15_000_000.0
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Risk & Penalty Fixes ---
        # Fix for 'LR_RESIDUAL': Reject trades if regression fit is too noisy.
        # Threshold: Standard Error of Estimate must be < 0.45% of current price.
        self.max_fit_error = 0.0045
        
        # Fix for 'Z:-3.93': Prevent catching falling knives.
        # We strictly gate entries between -2.6 (too deep/crash) and -1.6 (signal start).
        self.z_entry_floor = -2.6
        self.z_entry_ceiling = -1.6
        
        # Trend Filter: Avoid buying into steep downtrends even if Z-score is low.
        self.min_trend_slope = -0.0002
        
        # Confluence Filters
        self.rsi_max = 38
        self.max_daily_drop = -12.0  # Avoid assets down > 12% in 24h
        
        # --- State ---
        self.history = {} # symbol -> deque of prices
        self.positions = {} # symbol -> {'entry_price': float, 'entry_tick': int, 'amount': float}
        self.tick_count = 0
        
        # --- Pre-computed OLS Constants ---
        self.x = list(range(self.window_size))
        self.x_mean = statistics.mean(self.x)
        self.x_var_sum = sum((xi - self.x_mean) ** 2 for xi in self.x)

    def _calculate_metrics(self, price_deque):
        """
        Computes OLS regression metrics and RSI.
        Returns None if data is insufficient or invalid.
        """
        if len(price_deque) < self.window_size:
            return None
            
        y = list(price_deque)
        current_price = y[-1]
        y_mean = statistics.mean(y)
        
        # 1. Linear Regression (OLS)
        # Calculate Slope and Intercept
        covariance = sum((self.x[i] - self.x_mean) * (y[i] - y_mean) for i in range(self.window_size))
        slope = covariance / self.x_var_sum
        intercept = y_mean - slope * self.x_mean
        
        # 2. Residual Analysis (Fit Quality)
        # Calculate Sum of Squared Errors (SSE)
        sse = 0.0
        for i in range(self.window_size):
            predicted = slope * i + intercept
            sse += (y[i] - predicted) ** 2
            
        # Standard Error of the Estimate (Sigma)
        # Degrees of freedom = N - 2
        sigma = math.sqrt(sse / (self.window_size - 2))
        
        if sigma == 0:
            return None
            
        # Normalized Fit Error (Noise relative to price)
        fit_error = sigma / current_price
        
        # 3. Z-Score
        # Expected price at the current tick (last index)
        expected_price = slope * (self.window_size - 1) + intercept
        z_score = (current_price - expected_price) / sigma
        
        # 4. RSI (14 periods)
        rsi = 50.0
        if len(y) > 14:
            # Analyze last 15 points to get 14 diffs
            recent_prices = y[-15:]
            gains = 0.0
            losses = 0.0
            for i in range(1, len(recent_prices)):
                change = recent_prices[i] - recent_prices[i-1]
                if change > 0:
                    gains += change
                else:
                    losses += abs(change)
            
            if gains + losses > 0:
                avg_gain = gains / 14
                avg_loss = losses / 14
                if avg_loss == 0:
                    rsi = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100.0 - (100.0 / (1.0 + rs))

        return {
            'z_score': z_score,
            'fit_error': fit_error,
            'slope_pct': slope / current_price,
            'rsi': rsi,
            'price': current_price
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. State Maintenance
        # Clean history for removed symbols
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]

        # 2. Position Management (Exits)
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            amount = pos['amount']
            
            roi = (current_price - entry_price) / entry_price
            
            # Stop Loss (-2.5%)
            if roi < -0.025:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['STOP_LOSS']}
            
            # Take Profit (+1.2%)
            if roi > 0.012:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TAKE_PROFIT']}
                
            # Timeout (80 ticks)
            if self.tick_count - pos['entry_tick'] > 80:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TIMEOUT']}

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        # Filter and Sort Candidates by Liquidity
        candidates = []
        for s, data in prices.items():
            if data['liquidity'] >= self.min_liquidity:
                candidates.append(s)
        
        # Process candidates
        for symbol in candidates:
            price = prices[symbol]['priceUsd']
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            # Insufficient Data
            if len(self.history[symbol]) < self.window_size:
                continue
                
            # Already positioned
            if symbol in self.positions:
                continue

            # Calculate Technicals
            metrics = self._calculate_metrics(self.history[symbol])
            if not metrics:
                continue
                
            # --- SIGNAL CHECKS ---
            
            # FIX 1: LR_RESIDUAL
            # Reject if the trend is too noisy (poor fit)
            if metrics['fit_error'] > self.max_fit_error:
                continue
                
            # FIX 2: Z:-3.93
            # Strict Mean Reversion Band
            z = metrics['z_score']
            if not (self.z_entry_floor <= z <= self.z_entry_ceiling):
                continue
            
            # Filter: Slope
            # Prevent buying into a vertical crash
            if metrics['slope_pct'] < self.min_trend_slope:
                continue
                
            # Filter: RSI Confluence
            if metrics['rsi'] > self.rsi_max:
                continue
                
            # Filter: Daily Change
            # Avoid assets that have already crashed too hard today (>12%)
            if prices[symbol]['priceChange24h'] < self.max_daily_drop:
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
                'reason': ['LRMR_FIXED', f'Z:{z:.2f}']
            }
            
        return None