import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        self.window_size = 20
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        self.min_liquidity = 5_000_000.0
        
        # --- Momentum Parameters (Linear Regression) ---
        # We use the slope of Log(Price) to determine exponential growth rate.
        # This approach replaces penalized Z-Score/Band logic with pure vector momentum.
        # 0.0003 represents approx 0.03% growth per tick interval.
        self.min_log_slope = 0.0003
        
        # --- Risk Management ---
        self.trailing_stop_pct = 0.012  # 1.2% Trailing Stop (Tight)
        self.hard_stop_pct = 0.020      # 2.0% Hard Stop
        self.max_hold_ticks = 30        # Fast rotation
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0

    def calculate_log_slope(self, price_list):
        """
        Calculates the slope of the linear regression of log(prices).
        This normalizes price scale differences.
        """
        n = len(price_list)
        if n < 2: return 0.0
        
        # X axis is time [0, 1, ... n-1]
        x_sum = n * (n - 1) / 2
        xx_sum = n * (n - 1) * (2 * n - 1) / 6
        
        # Y axis is log(price)
        y_vals = [math.log(p) for p in price_list]
        y_sum = sum(y_vals)
        xy_sum = sum(i * y for i, y in enumerate(y_vals))
        
        # Slope formula: (N*Sum(xy) - Sum(x)*Sum(y)) / (N*Sum(xx) - Sum(x)^2)
        numerator = n * xy_sum - x_sum * y_sum
        denominator = n * xx_sum - x_sum * x_sum
        
        if denominator == 0: return 0.0
        return numerator / denominator

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Prune State
        current_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in current_symbols:
                del self.history[s]

        # 2. Update History
        for s, data in prices.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.window_size)
            self.history[s].append(data['priceUsd'])

        # 3. Manage Positions
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # Update High Water Mark
            if current_price > pos['high_water_mark']:
                pos['high_water_mark'] = current_price
            
            hwm = pos['high_water_mark']
            entry_price = pos['entry_price']
            
            drawdown = (current_price - hwm) / hwm
            pnl = (current_price - entry_price) / entry_price
            
            exit_reason = None
            
            if drawdown <= -self.trailing_stop_pct:
                exit_reason = 'TRAILING_STOP'
            elif pnl <= -self.hard_stop_pct:
                exit_reason = 'HARD_STOP'
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

        # 4. Entry Scan
        if len(self.positions) >= self.max_positions:
            return None

        # Filter candidates by liquidity
        candidates = []
        for s, data in prices.items():
            if data['liquidity'] >= self.min_liquidity:
                candidates.append(s)
        
        # Sort by Volume to prioritize high activity (Momentum preference)
        candidates.sort(key=lambda s: prices[s]['volume24h'], reverse=True)
        
        for symbol in candidates:
            if symbol in self.positions: continue
            
            history = self.history[symbol]
            if len(history) < self.window_size:
                continue

            hist_list = list(history)
            current_price = hist_list[-1]
            
            # --- Anti-Pattern Logic ---
            
            # A. Avoid DIP_BUY: 
            # STRICT REQUIREMENT: Price must be ABOVE the Moving Average.
            # Dip buyers buy below the mean; we buy above it (Trend Following).
            sma = sum(hist_list) / len(hist_list)
            if current_price <= sma:
                continue
                
            # B. Avoid KELTNER / OVERSOLD:
            # Instead of Band logic or oscillators, we use Linear Regression Slope.
            # We require positive velocity.
            slope = self.calculate_log_slope(hist_list)
            
            if slope > self.min_log_slope:
                
                # C. Confirmation
                # Ensure the candle is green (immediate buying pressure)
                prev_price = hist_list[-2]
                if current_price > prev_price:
                    
                    amount = self.trade_size_usd / current_price
                    self.positions[symbol] = {
                        'entry_price': current_price,
                        'high_water_mark': current_price,
                        'amount': amount,
                        'entry_tick': self.tick_count
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['LOG_REG_MOMENTUM']
                    }
            
        return None