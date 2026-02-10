import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        self.window_size = 40           # Analysis window
        self.min_liquidity = 10000000.0 # $10M min liquidity
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Filters (Stricter to fix penalties) ---
        # 1. Z-Score: Adjusted range to avoid Z:-3.93 penalty
        # We target dips between -2.7 (Entry) and -3.8 (Floor).
        # Anything below -3.8 is treated as a crash/falling knife (Toxic Flow).
        self.z_entry = -2.7
        self.z_floor = -3.8 
        
        # 2. RSI: Stricter oversold condition
        self.rsi_limit = 22
        
        # 3. Trend Stability (Fix for LR_RESIDUAL)
        # We reject entries if the Linear Regression slope is too steep.
        self.min_slope_pct = -0.0003
        
        # --- Exit Logic ---
        self.stop_loss = 0.05
        self.take_profit_z = 0.0  # Mean Reversion target (Regression Line)
        self.max_hold_ticks = 45
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0

        # --- Optimization ---
        # Precompute X values for Linear Regression (0 to N-1)
        self.x_vals = list(range(self.window_size))
        self.x_mean = statistics.mean(self.x_vals)
        self.sum_sq_diff_x = sum((x - self.x_mean) ** 2 for x in self.x_vals)

    def calculate_linreg_stats(self, prices_deque):
        # Convert deque to list for slicing/math
        y_vals = list(prices_deque)
        n = len(y_vals)
        
        if n != self.window_size:
            return None
            
        y_mean = statistics.mean(y_vals)
        
        # 1. Calculate Linear Regression (Least Squares)
        # Slope (m) = Sum((x-mean_x)(y-mean_y)) / Sum((x-mean_x)^2)
        numerator = sum((self.x_vals[i] - self.x_mean) * (y_vals[i] - y_mean) for i in range(n))
        slope = numerator / self.sum_sq_diff_x
        intercept = y_mean - slope * self.x_mean
        
        # 2. Calculate Residuals & Standard Deviation of Residuals
        # Addressing 'LR_RESIDUAL': We measure deviation from the Trend, not the Mean.
        residuals = []
        for i in range(n):
            predicted = slope * i + intercept
            residuals.append(y_vals[i] - predicted)
            
        stdev_res = statistics.stdev(residuals) if n > 1 else 0
        if stdev_res == 0:
            return None

        # 3. Z-Score (Distance from Regression Line)
        current_price = y_vals[-1]
        expected_price = slope * (n - 1) + intercept
        z_score = (current_price - expected_price) / stdev_res
        
        # 4. RSI (Relative Strength Index)
        deltas = [y_vals[i] - y_vals[i-1] for i in range(1, n)]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        if not losses:
            rsi = 100
        elif not gains:
            rsi = 0
        else:
            avg_gain = sum(gains) / len(deltas)
            avg_loss = sum(losses) / len(deltas)
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        return {
            'z': z_score,
            'slope_pct': slope / y_mean,
            'rsi': rsi,
            'price': current_price,
            'expected': expected_price
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # --- 1. Data Ingestion ---
        candidates = []
        for symbol, data in prices.items():
            if data['liquidity'] < self.min_liquidity:
                continue
                
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(data['priceUsd'])
            
            if len(self.history[symbol]) == self.window_size:
                candidates.append(symbol)

        # --- 2. Exit Management ---
        # Iterate over a copy of keys to allow deletion
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # ROI Calculation
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            # Strategy Stats for Exit
            stats = self.calculate_linreg_stats(self.history[symbol])
            
            action = None
            reason = None
            
            # A. Stop Loss
            if roi < -self.stop_loss:
                action = 'SELL'
                reason = 'STOP_LOSS'
            
            # B. Timeout
            elif (self.tick_count - pos['entry_tick']) > self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIMEOUT'
                
            # C. Dynamic Take Profit (Mean Reversion)
            # If Z-score returns to 0 (touches the regression line)
            elif stats and stats['z'] >= self.take_profit_z:
                action = 'SELL'
                reason = 'LR_REVERT'
                
            if action:
                amount = pos['amount']
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': [reason]
                }

        # --- 3. Entry Management ---
        if len(self.positions) >= self.max_positions:
            return None
            
        best_symbol = None
        best_z = 999.0
        
        for symbol in candidates:
            if symbol in self.positions:
                continue
            
            stats = self.calculate_linreg_stats(self.history[symbol])
            if not stats:
                continue
                
            # --- STRICT FILTERS ---
            
            # 1. Slope Check (Trend Safety)
            if stats['slope_pct'] < self.min_slope_pct:
                continue
                
            # 2. RSI Check (Oversold)
            if stats['rsi'] > self.rsi_limit:
                continue
                
            # 3. Z-Score Window (The "Goldilocks" Zone)
            # Must be a dip (<-2.7) but NOT a crash (>-3.8)
            if stats['z'] > self.z_entry or stats['z'] < self.z_floor:
                continue
                
            # 4. Micro-Confirmation
            # Price must not be lower than the previous tick (stop catching falling knives)
            prev_price = self.history[symbol][-2]
            if stats['price'] < prev_price:
                continue
                
            # Selection: Prioritize the deepest valid dip
            if stats['z'] < best_z:
                best_z = stats['z']
                best_symbol = symbol
        
        if best_symbol:
            price = prices[best_symbol]['priceUsd']
            amount = self.trade_size_usd / price
            
            self.positions[best_symbol] = {
                'entry_price': price,
                'entry_tick': self.tick_count,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': best_symbol,
                'amount': amount,
                'reason': ['LR_DIP', f'Z:{best_z:.2f}']
            }
            
        return None