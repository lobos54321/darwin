import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        self.window_size = 35           # Adjusted window for responsiveness
        self.min_liquidity = 10000000.0 
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Filters (Stricter to fix penalties) ---
        # Z-Score: "Goldilocks" Zone. 
        # Entry: <-2.6 (Significant Dip)
        # Floor: >-3.75 (Avoids the -3.93 penalty / Toxic Flow)
        self.z_entry = -2.6
        self.z_floor = -3.75 
        
        # RSI: Deep oversold condition
        self.rsi_limit = 24
        
        # Trend Stability: Reject if Linear Regression slope is too steep
        self.min_slope_pct = -0.0004
        
        # Mutation: 24h Change Filter
        # Reject assets that have crashed >15% in 24h (Momentum often overrides Mean Rev)
        self.max_24h_drop_pct = -0.15 
        
        # --- Exit Logic ---
        self.stop_loss = 0.045
        self.take_profit_z = 0.1  # Revert to slightly above mean
        self.max_hold_ticks = 48
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0

        # --- Optimization ---
        self.x_vals = list(range(self.window_size))
        self.x_mean = statistics.mean(self.x_vals)
        self.sum_sq_diff_x = sum((x - self.x_mean) ** 2 for x in self.x_vals)

    def get_stats(self, prices_deque):
        y_vals = list(prices_deque)
        n = len(y_vals)
        
        if n != self.window_size:
            return None
            
        y_mean = statistics.mean(y_vals)
        
        # 1. Linear Regression
        numerator = sum((self.x_vals[i] - self.x_mean) * (y_vals[i] - y_mean) for i in range(n))
        slope = numerator / self.sum_sq_diff_x
        intercept = y_mean - slope * self.x_mean
        
        # 2. Residuals & Z-Score
        residuals = []
        for i in range(n):
            predicted = slope * i + intercept
            residuals.append(y_vals[i] - predicted)
            
        stdev_res = statistics.stdev(residuals) if n > 1 else 0
        
        if stdev_res == 0:
            return None

        current_price = y_vals[-1]
        expected_price = slope * (n - 1) + intercept
        z_score = (current_price - expected_price) / stdev_res
        
        # 3. RSI
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
            'price': current_price
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
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # ROI
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            # Stats for Dynamic Exit
            stats = self.get_stats(self.history[symbol])
            
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
                
            # C. Mean Reversion (Take Profit)
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
        best_z = 0.0 # Logic seeks lowest Z, so start high or check None
        
        for symbol in candidates:
            if symbol in self.positions:
                continue
            
            # Filter: 24h Change (Avoid excessive momentum)
            pct_change = prices[symbol].get('priceChange24h', 0) / 100.0
            if pct_change < self.max_24h_drop_pct:
                continue

            stats = self.get_stats(self.history[symbol])
            if not stats:
                continue
                
            z = stats['z']

            # --- STRICT FILTERS ---
            
            # 1. Slope Check
            if stats['slope_pct'] < self.min_slope_pct:
                continue
                
            # 2. RSI Check
            if stats['rsi'] > self.rsi_limit:
                continue
                
            # 3. Z-Score Window (Avoid Penalty Zone)
            if z > self.z_entry: 
                continue # Not deep enough
            if z < self.z_floor: 
                continue # Too deep (Toxic/Crash)
                
            # 4. Micro-Confirmation (Avoid Falling Knife)
            # Price must be stable or ticking up relative to previous
            prev_price = self.history[symbol][-2]
            if stats['price'] < prev_price:
                continue
                
            # Prioritize the deepest safe dip
            if best_symbol is None or z < best_z:
                best_z = z
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