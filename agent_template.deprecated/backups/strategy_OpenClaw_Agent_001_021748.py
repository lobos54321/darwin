import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        # Mutation: Slightly larger window (35) to capture more robust trends
        self.window_size = 35
        # Mutation: Increased liquidity/volume thresholds to reduce noise and slippage
        self.min_liquidity = 20_000_000.0
        self.min_volume_24h = 10_000_000.0
        
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Penalty Fixes ---
        # Fix for 'LR_RESIDUAL': Stricter Standard Error of Estimate (0.35%)
        # If price deviates too wildly from the regression line, it's too risky.
        self.max_fit_error = 0.0035 
        
        # Fix for 'Z:-3.93': Strict Z-Score Band
        # Floor at -2.6 to avoid "falling knives" (structural breaks).
        # Ceiling at -1.6 to ensure sufficient mean reversion potential.
        self.z_entry_floor = -2.6
        self.z_entry_ceiling = -1.6
        
        # --- Filters ---
        self.min_trend_slope = -0.0002  # Reject steep downtrends
        self.rsi_max = 30               # Stricter oversold condition
        self.max_daily_drop = -0.08     # Avoid assets down > 8% in 24h
        
        # --- State ---
        self.history = {} # symbol -> deque of prices
        self.positions = {} # symbol -> position info
        self.tick_count = 0
        
        # --- Pre-computed OLS Constants ---
        self.x = list(range(self.window_size))
        self.x_mean = statistics.mean(self.x)
        self.x_var_sum = sum((xi - self.x_mean) ** 2 for xi in self.x)

    def _calculate_rsi(self, prices_list):
        """Calculates simple RSI for speed."""
        if len(prices_list) < 15:
            return 50.0
        
        # Analyze last 14 changes
        changes = []
        for i in range(len(prices_list) - 14, len(prices_list)):
            changes.append(prices_list[i] - prices_list[i-1])
            
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
        
        # 1. State Maintenance
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
            
            # Logic: Tight Stop, Quick Profit
            if roi < -0.020: # Stop Loss -2.0%
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['STOP_LOSS']}
            
            if roi > 0.012: # Take Profit +1.2%
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TAKE_PROFIT']}
                
            if self.tick_count - pos['entry_tick'] > 50: # Timeout (Reduced)
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TIMEOUT']}

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        # Filter candidates by Liquidity & Volume
        candidates = []
        for s, data in prices.items():
            if data['liquidity'] >= self.min_liquidity and data.get('volume24h', 0) >= self.min_volume_24h:
                candidates.append(s)
        
        # Mutation: Sort by Liquidity (safest first)
        candidates.sort(key=lambda s: prices[s]['liquidity'], reverse=True)
        
        for symbol in candidates:
            price = prices[symbol]['priceUsd']
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) < self.window_size:
                continue
            
            if symbol in self.positions:
                continue

            # --- OLS Calculation ---
            y = list(self.history[symbol])
            y_mean = statistics.mean(y)
            
            # Slope
            covariance = sum((self.x[i] - self.x_mean) * (y[i] - y_mean) for i in range(self.window_size))
            slope = covariance / self.x_var_sum
            intercept = y_mean - slope * self.x_mean
            
            # Residuals (SSE)
            sse = 0.0
            for i in range(self.window_size):
                pred = slope * i + intercept
                sse += (y[i] - pred) ** 2
            
            if sse < 1e-10: continue
            
            # Metrics
            sigma = math.sqrt(sse / (self.window_size - 2))
            fit_error = sigma / price
            expected_price = slope * (self.window_size - 1) + intercept
            z_score = (price - expected_price) / sigma
            
            # --- Signal Validation ---
            
            # 1. Fix LR_RESIDUAL: Reject high noise
            if fit_error > self.max_fit_error:
                continue
                
            # 2. Fix Z:-3.93: Strict Reversion Band
            if not (self.z_entry_floor <= z_score <= self.z_entry_ceiling):
                continue
                
            # 3. Slope Check (Trend)
            if (slope / price) < self.min_trend_slope:
                continue
                
            # 4. RSI Check
            rsi = self._calculate_rsi(y)
            if rsi > self.rsi_max:
                continue
                
            # 5. Crash Protection
            if prices[symbol]['priceChange24h'] < self.max_daily_drop:
                continue

            # --- Execute ---
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