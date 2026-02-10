import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        # Mutation: Increased window size slightly to smooth out noise (32 vs 30)
        self.window_size = 32
        self.min_liquidity = 18_000_000.0
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Penalties Fixes ---
        # Fix for 'LR_RESIDUAL': 
        # Tighter threshold for Standard Error of Estimate. 
        # If the regression channel is too loose (high noise), we skip.
        self.max_fit_error = 0.0040  # Stricter than previous 0.0045
        
        # Fix for 'Z:-3.93':
        # Strict Entry Band. We reject Z-scores beyond -2.5 (potential crash/knife).
        # We reject Z-scores above -1.7 (not enough mean reversion potential).
        self.z_entry_floor = -2.5
        self.z_entry_ceiling = -1.7
        
        # --- Filters ---
        # Slope Filter: Avoid buying into steep downtrends
        self.min_trend_slope = -0.00018
        
        # RSI Filter: Stricter overbought/sold check
        self.rsi_max = 32
        
        # Daily Drawdown Filter: Avoid assets crashing > 10%
        self.max_daily_drop = -0.10
        
        # --- State ---
        self.history = {} # symbol -> deque of prices
        self.positions = {} # symbol -> position info
        self.tick_count = 0
        
        # --- Pre-computed OLS Constants ---
        self.x = list(range(self.window_size))
        self.x_mean = statistics.mean(self.x)
        self.x_var_sum = sum((xi - self.x_mean) ** 2 for xi in self.x)

    def _calculate_metrics(self, price_deque):
        """
        Computes OLS regression metrics and RSI efficiently.
        """
        if len(price_deque) < self.window_size:
            return None
            
        y = list(price_deque)
        current_price = y[-1]
        y_mean = statistics.mean(y)
        
        # 1. Linear Regression (OLS)
        # Slope (Beta) = Cov(x,y) / Var(x)
        covariance = sum((self.x[i] - self.x_mean) * (y[i] - y_mean) for i in range(self.window_size))
        slope = covariance / self.x_var_sum
        intercept = y_mean - slope * self.x_mean
        
        # 2. Residual Analysis (Fit Quality)
        sse = 0.0
        for i in range(self.window_size):
            predicted = slope * i + intercept
            sse += (y[i] - predicted) ** 2
            
        # Standard Error (Sigma) with DOF = N - 2
        # Guard against perfect fit (div by zero)
        if sse <= 1e-9:
            return None
            
        sigma = math.sqrt(sse / (self.window_size - 2))
        
        # Normalized Fit Error (Noise relative to price)
        fit_error = sigma / current_price
        
        # 3. Z-Score
        # Expected price at the current tick (last index)
        expected_price = slope * (self.window_size - 1) + intercept
        z_score = (current_price - expected_price) / sigma
        
        # 4. RSI (14 periods) - Mutation: Simple averaging for speed
        rsi = 50.0
        if len(y) > 14:
            subset = y[-15:]
            gains = 0.0
            losses = 0.0
            for i in range(1, len(subset)):
                change = subset[i] - subset[i-1]
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
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]

        # 2. Position Management (Exits First)
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            amount = pos['amount']
            
            roi = (current_price - entry_price) / entry_price
            
            # Stop Loss (Tightened to -2.2%)
            if roi < -0.022:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['STOP_LOSS']}
            
            # Take Profit (+1.4%)
            if roi > 0.014:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TAKE_PROFIT']}
                
            # Timeout (Reduced to 60 ticks for faster cycling)
            if self.tick_count - pos['entry_tick'] > 60:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TIMEOUT']}

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        # Filter candidates
        candidates = []
        for s, data in prices.items():
            # Added volume check for higher quality pairs
            if data['liquidity'] >= self.min_liquidity and data.get('volume24h', 0) > 5_000_000:
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
            # If the regression fit is noisy (>0.40% error), the mean reversion assumption is weak.
            if metrics['fit_error'] > self.max_fit_error:
                continue
                
            # FIX 2: Z:-3.93
            # Strict Band: Must be oversold (-1.7) but not crashing (-2.5)
            z = metrics['z_score']
            if not (self.z_entry_floor <= z <= self.z_entry_ceiling):
                continue
            
            # Filter: Slope
            if metrics['slope_pct'] < self.min_trend_slope:
                continue
                
            # Filter: RSI
            if metrics['rsi'] > self.rsi_max:
                continue
                
            # Filter: Daily Change
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
                'reason': ['OLS_V2', f'Z:{z:.2f}']
            }
            
        return None