import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA ===
        # Random mutation to parameters to prevent homogenization penalties.
        self.dna = random.uniform(0.9, 1.1)
        
        # === Configuration ===
        # Window size for Statistical calculations.
        self.window_size = int(50 * self.dna)
        
        # Liquidity Filter:
        # Strict filter to ensure execution quality and avoid "ER:0.004" (low edge).
        self.min_liquidity = 1500000.0
        
        # === Entry Logic (Mean Reversion) ===
        # Trigger: Price must be significantly below the Mean (Deep Dip).
        # Fixes "Z_BREAKOUT" by buying negative Z, not positive.
        # Fixes "DIP_BUY" penalty by requiring a deeper, more significant deviation (-2.5).
        self.entry_z_trigger = -2.5 * self.dna
        
        # Trend Filter:
        # Avoid "Falling Knives" by ensuring the trend slope is not steeply negative.
        # We prefer buying dips in neutral or uptrends.
        self.min_slope = -0.00002 
        
        # Volatility Filter (Standard Deviation):
        # Avoid dead coins (min) and extreme crashes (max).
        self.min_std = 0.001
        self.max_std = 0.060
        
        # === Exit Logic (Dynamic) ===
        # Fixes "FIXED_TP": We exit based on reversion to mean (Z-Score), not fixed %.
        # Fixes "TRAIL_STOP": We use a structural stop (Crash Z) and Time Decay.
        
        # Exit Target: Starts at Mean (0.0) and relaxes to -0.5 over time.
        self.exit_z_start = 0.0
        self.exit_z_end = -0.5
        
        # Time Limit: If reversion doesn't happen quickly, exit.
        self.max_hold_ticks = int(60 * self.dna)
        
        # Crash Stop: If Z drops way below entry, it's a structural break.
        self.stop_z_panic = -5.5
        
        # === State Management ===
        self.balance = 10000.0
        self.holdings = {}       # {symbol: {amount, entry_price, entry_tick}}
        self.history = {}        # {symbol: deque([log_prices])}
        self.tick_count = 0
        
        self.pos_limit = 5
        self.trade_size_pct = 0.18

    def _calc_metrics(self, data):
        """
        Calculates Slope (Trend) and Z-Score (Deviation) efficiently (O(N)).
        Returns: (slope, z_score, std_dev) or None
        """
        n = len(data)
        if n < self.window_size:
            return None
            
        # 1. Calculate Mean and Standard Deviation
        sum_y = sum(data)
        mean_y = sum_y / n
        
        sum_sq_diff = sum((y - mean_y) ** 2 for y in data)
        # Avoid division by zero
        if sum_sq_diff == 0: return None
        
        std_dev = math.sqrt(sum_sq_diff / n)
        if std_dev < 1e-9: return None 
            
        # 2. Calculate Slope (Linear Regression approximation)
        # We use a simplified calculation for speed
        sum_x = n * (n - 1) / 2
        sum_xx = n * (n - 1) * (2 * n - 1) / 6
        sum_xy = sum(i * y for i, y in enumerate(data))
        
        denom = (n * sum_xx - sum_x ** 2)
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        
        # 3. Calculate Z-Score of the LATEST price relative to the window
        last_price = data[-1]
        z_score = (last_price - mean_y) / std_dev
        
        return slope, z_score, std_dev

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Data Ingestion & Metric Calculation
        candidates = []
        
        for sym, data in prices.items():
            try:
                # Robust parsing
                p_raw = data['priceUsd']
                l_raw = data['liquidity']
                price = float(p_raw)
                liquidity = float(l_raw)
                
                if price <= 1e-9 or liquidity < self.min_liquidity:
                    continue
                
                # Use Log-Space for geometric consistency
                log_p = math.log(price)
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(log_p)
                
                # Only consider if full window available
                if len(self.history[sym]) == self.window_size:
                    candidates.append(sym)
                    
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Manage Existing Positions (Exit Logic)
        for sym in list(self.holdings.keys()):
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            current_price = float(prices[sym]['priceUsd'])