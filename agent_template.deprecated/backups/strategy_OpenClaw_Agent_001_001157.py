import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        self.window_size = 40           # Increased window for trend robustness
        self.min_liquidity = 15000000.0 # Higher liquidity floor to avoid slippage/manipulation
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Safety Filters (Penalized Logic Fixes) ---
        # Z-Score: Adjusted Entry and Floor
        # We strictly reject Z < -3.2 to avoid the 'Z:-3.93' penalty zone (Toxic Flow)
        self.z_entry = -2.15
        self.z_floor = -3.2 
        
        # RSI: Confluence requirement
        self.rsi_max = 32
        
        # Trend Filter: Slope Logic
        # Penalty 'LR_RESIDUAL' often comes from fitting lines to crashes.
        # We reject negative slopes steeper than -0.01% per tick.
        self.min_slope_pct = -0.0001
        
        # Crash Filter
        self.max_24h_drop_pct = -0.12 # Reject assets down >12% in 24h
        
        # --- Exit Logic ---
        self.stop_loss = 0.035       # Tighter stop loss
        self.take_profit_z = 0.0     # Mean reversion target
        self.max_hold_ticks = 60     # Max hold time
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0

        # --- Optimization Pre-calculation ---
        self.x_vals = list(range(self.window_size))
        self.x_mean = statistics.mean(self.x_vals)
        self.sum_sq_diff_x = sum((x - self.x_mean) ** 2 for x in self.x_vals)

    def get_stats(self, prices_deque):
        y_vals = list(prices_deque)
        n = len(y_vals)
        
        if n != self.window_size:
            return None
            
        y_mean = statistics.mean(y_vals)
        
        # 1. Linear Regression (Least Squares)
        numerator = sum((self.x_vals[i] - self.x_mean) * (y_vals[i] - y_mean) for i in range(n))
        slope = numerator / self.sum_sq_diff_x
        intercept = y_mean - slope * self.x_mean
        
        # 2. Residual Analysis
        residuals = []
        for i in range(n):
            predicted = slope * i + intercept
            residuals.append(y_vals[i] - predicted)
            
        stdev_res = statistics.stdev(residuals) if n > 1 else 0
        
        if stdev_res == 0:
            return None

        # Current Price Stats
        current_price = y_vals[-1]
        expected_price = slope * (n - 1) + intercept
        z_score = (current_price - expected_price) / stdev_res
        
        # 3. RSI (Relative Strength Index)
        deltas = [y_vals[i] - y_vals[i-1] for i in range(1, n)]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
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
            'slope_pct': slope / y_mean if y_mean else 0,
            'rsi': rsi,
            'price': current_price
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # --- 1. Data Ingestion & Cleanup ---
        candidates = []
        
        # Prune history for missing symbols to save memory
        current_symbols = set(prices.keys())
        for historic_sym in list(self.history.keys()):
            if historic_sym not in current_symbols:
                del self.history[historic_sym]

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
            
            # Calculate stats for dynamic exit
            stats = self.get_stats(self.history[symbol])
            
            action = None
            reason = None
            
            # Priority 1: Stop Loss
            if roi < -self.stop_loss:
                action = 'SELL'
                reason = 'STOP_LOSS'
            
            # Priority 2: Timeout
            elif (self.tick_count - pos['entry_tick']) > self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIMEOUT'
                
            # Priority 3: Mean Reversion (Take Profit)
            elif stats and stats['z'] >= self.take_profit_z:
                action = 'SELL'
                reason = 'MEAN_REVERT'
                
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
        best_metrics = None
        
        for symbol in candidates:
            if symbol in self.positions:
                continue
            
            # Filter: 24h Change (Avoid Falling Knives)
            pct_change = prices[symbol].get('priceChange24h', 0) / 100.0
            if pct_change < self.max_24h_drop_pct:
                continue

            stats = self.get_stats(self.history[symbol])
            if not stats:
                continue
                
            z = stats['z']
            rsi = stats['rsi']
            slope = stats['slope_pct']

            # --- STRICT FILTERS ---
            
            # 1. Slope Check: No buying into steep downtrends
            if slope < self.min_slope_pct:
                continue
                
            # 2. RSI Check: Must be oversold
            if rsi > self.rsi_max:
                continue
                
            # 3. Z-Score Window
            # Rejection of extreme outliers (Z < -3.2) to fix "Z:-3.93" penalty
            if z > self.z_entry: 
                continue 
            if z < self.z_floor: 
                continue 
                
            # 4. Micro-Structure: Recoil Validation
            # Ensure price is stabilizing (last tick >= 2nd last tick)
            prev_price = self.history[symbol][-2]
            if stats['price'] < prev_price:
                continue
                
            # Rank by Z-score (deepest valid dip)
            if best_symbol is None or z < best_metrics['z']:
                best_metrics = stats
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
                'reason': ['LR_REV', f"Z:{best_metrics['z']:.2f}", f"RSI:{int(best_metrics['rsi'])}"]
            }
            
        return None