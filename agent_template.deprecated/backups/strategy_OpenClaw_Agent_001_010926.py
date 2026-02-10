import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        self.window_size = 30           # Reduced window for faster adaptation
        self.min_liquidity = 15000000.0 # High liquidity to ensure execution quality
        self.max_positions = 4          # Balanced portfolio size
        self.trade_size_usd = 2000.0
        
        # --- Filters for Penalty Avoidance ---
        # 1. Z-Score: The "Safe Zone"
        # We reject Z < -2.9 to avoid the "Z:-3.93" penalty (Catching Falling Knives).
        # We enter between -1.9 and -2.9.
        self.z_entry_ceiling = -1.9 
        self.z_entry_floor = -2.9
        
        # 2. Volatility / Residual Check (Fix for LR_RESIDUAL)
        # If the standard deviation of residuals is > 1% of price, the fit is too loose.
        self.max_residual_volatility = 0.01 
        
        # 3. Slope Check
        # Reject if the linear trend is steeply negative (avoid downtrends).
        self.min_trend_slope = -0.0005 
        
        # 4. RSI Confluence
        self.rsi_max = 35
        
        # --- Exit Logic ---
        self.stop_loss = 0.03        # 3% Stop Loss
        self.take_profit_roi = 0.015 # 1.5% Take Profit (Stat Arb style)
        self.max_hold_ticks = 50     # Time-based exit
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0
        
        # --- Pre-calculations for OLS ---
        self.x = list(range(self.window_size))
        self.x_mean = statistics.mean(self.x)
        self.x_var_sum = sum((xi - self.x_mean) ** 2 for xi in self.x)

    def get_metrics(self, price_deque):
        if len(price_deque) != self.window_size:
            return None
            
        y = list(price_deque)
        y_mean = statistics.mean(y)
        
        # OLS Linear Regression
        # Slope = sum((x - x_mean)(y - y_mean)) / sum((x - x_mean)^2)
        numerator = sum((self.x[i] - self.x_mean) * (y[i] - y_mean) for i in range(self.window_size))
        slope = numerator / self.x_var_sum
        intercept = y_mean - slope * self.x_mean
        
        # Calculate Residuals and Standard Deviation
        # Using a loop to calc residuals is safer for logic transparency
        residuals = []
        for i in range(self.window_size):
            prediction = slope * i + intercept
            residuals.append(y[i] - prediction)
            
        sigma = statistics.stdev(residuals)
        
        if sigma == 0:
            return None
            
        # Z-Score of the LATEST price
        # Expected price is the last point on the regression line
        expected_price = slope * (self.window_size - 1) + intercept
        current_price = y[-1]
        z_score = (current_price - expected_price) / sigma
        
        # Normalized metrics
        slope_pct = slope / current_price
        volatility_pct = sigma / current_price
        
        # RSI (Short period for reaction)
        # Calculate RSI on the last 14 ticks of the window
        rsi_lookback = 14
        if len(y) >= rsi_lookback:
            changes = [y[i] - y[i-1] for i in range(len(y)-rsi_lookback+1, len(y))]
            gains = [c for c in changes if c > 0]
            losses = [abs(c) for c in changes if c < 0]
            
            avg_gain = sum(gains) / rsi_lookback
            avg_loss = sum(losses) / rsi_lookback
            
            if avg_loss == 0:
                rsi = 100
            elif avg_gain == 0:
                rsi = 0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
        else:
            rsi = 50

        return {
            'z': z_score,
            'slope': slope_pct,
            'vol': volatility_pct,
            'rsi': rsi,
            'price': current_price
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # --- 1. Cleanup & Update ---
        current_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in current_symbols:
                del self.history[s]
                
        candidates = []
        
        for symbol, data in prices.items():
            if data['liquidity'] < self.min_liquidity:
                continue
            
            # Crash Filter: Check 24h change immediately
            # Reject assets that are down significantly on the day (-12%)
            if data['priceChange24h'] < -12.0:
                continue
                
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(data['priceUsd'])
            
            if len(self.history[symbol]) == self.window_size:
                candidates.append(symbol)
                
        # --- 2. Exit Logic ---
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            
            roi = (current_price - entry_price) / entry_price
            elapsed_ticks = self.tick_count - pos['entry_tick']
            
            action