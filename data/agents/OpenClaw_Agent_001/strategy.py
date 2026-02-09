import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Configuration ---
        self.window_size = 20
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        self.min_liquidity = 3_000_000.0  # Filter for liquid pairs
        
        # --- Breakout & Momentum Logic ---
        # Instead of dip buying, we target 'Smooth Breakouts'.
        # We look for high linear regression slope (velocity) combined with 
        # high R-squared (consistency).
        self.min_slope = 0.0004       # Min log-price growth per tick
        self.min_r_squared = 0.75     # Min correlation (trend smoothness)
        
        # --- Risk Management ---
        self.stop_loss_pct = 0.02     # Hard Stop 2%
        self.trailing_arm_pct = 0.01  # Profit needed to arm trailing stop
        self.trailing_dist_pct = 0.005 # Trailing distance 0.5%
        self.max_hold_ticks = 40      # Rotate capital quickly
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0

    def get_trend_stats(self, prices):
        """
        Calculates the Linear Regression Slope and R-Squared of Log(Prices).
        High Slope + High R2 = Strong, Clean Momentum.
        """
        n = len(prices)
        if n < 5: return 0.0, 0.0
        
        x_vals = list(range(n))
        y_vals = [math.log(p) for p in prices]
        
        sum_x = sum(x_vals)
        sum_y = sum(y_vals)
        sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
        sum_xx = sum(x * x for x in x_vals)
        
        # Calculate Slope (m)
        numerator = (n * sum_xy) - (sum_x * sum_y)
        denominator = (n * sum_xx) - (sum_x * sum_x)
        
        if denominator == 0: return 0.0, 0.0
        slope = numerator / denominator
        
        # Calculate Intercept (b)
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate R-Squared
        y_pred = [slope * x + intercept for x in x_vals]
        mean_y = sum_y / n
        ss_tot = sum((y - mean_y) ** 2 for y in y_vals)
        ss_res = sum((y - yp) ** 2 for y, yp in zip(y_vals, y_pred))
        
        if ss_tot == 0: return slope, 0.0
        r_squared = 1 - (ss_res / ss_tot)
        
        return slope, r_squared

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Prune & Update History
        current_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in current_symbols:
                del self.history[s]
                
        for s, data in prices.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.window_size)
            self.history[s].append(data['priceUsd'])

        # 2. Position Management (Exits)
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            
            # Update High Water Mark
            if current_price > pos['high_water_mark']:
                pos['high_water_mark'] = current_price
            
            roi = (current_price - entry_price) / entry_price
            dd_from_top = (current_price - pos['high_water_mark']) / pos['high_water_mark']
            
            exit_reason = None
            
            # Stop Loss (Catastrophic protection)
            if roi <= -self.stop_loss_pct:
                exit_reason = 'STOP_LOSS'
            
            # Trailing Stop
            # Only active if we are/were in profit > arming pct
            elif (pos['high_water_mark'] / entry_price) - 1 >= self.trailing_arm_pct:
                if dd_from_top <= -self.trailing_dist_pct:
                    exit_reason = 'TRAILING_STOP'
            
            # Time Decay Exit
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

        # 3. Entry Logic (Scan)
        if len(self.positions) >= self.max_positions:
            return None
        
        # Filter: High Liquidity Only
        candidates = [s for s, d in prices.items() if d['liquidity'] >= self.min_liquidity]
        
        # Sort: Prioritize assets with highest 24h Change (Trend Following)
        # This naturally pushes us away from "Dip Buying" towards "Strength Buying".
        candidates.sort(key=lambda s: prices[s]['priceChange24h'], reverse=True)
        
        for symbol in candidates:
            if symbol in self.positions: continue
            
            hist = self.history[symbol]
            if len(hist) < self.window_size: continue
            
            price_list = list(hist)
            current_price = price_list[-1]
            
            # --- Anti-Penalty Logic ---
            # To fix DIP_BUY, we strictly buy BREAKOUTS.
            # Condition 1: Current Price must be >= Highest price of previous (N-1) ticks.
            # This is a Donchian Channel Breakout logic.
            past_prices = price_list[:-1]
            local_high = max(past_prices)
            
            if current_price < local_high:
                # Not a breakout -> Skip
                continue
                
            # Condition 2: Smooth Momentum (Slope & R2)
            slope, r2 = self.get_trend_stats(price_list)
            
            if slope >= self.min_slope and r2 >= self.min_r_squared:
                
                # Condition 3: Positive Volume Confirmation (Optional but good)
                # Ensure 24h change is positive
                if prices[symbol]['priceChange24h'] > 0:
                
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
                        'reason': ['BREAKOUT_MOMENTUM', f'SLOPE_{slope:.5f}']
                    }

        return None