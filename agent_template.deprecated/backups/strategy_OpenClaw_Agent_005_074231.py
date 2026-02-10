import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity ===
        # Unique seed to differentiate parameters from other instances (Hive Mind avoidance).
        self.dna = random.random()
        
        # === Lookback Window ===
        # A variable window size (approx 2.5 - 3.5 hours) to prevent synchronized signal generation.
        self.window_size = 150 + int(self.dna * 60)
        
        # === Filters ===
        self.min_liquidity = 6_000_000.0
        
        # === Signal Logic: Statistical Mean Reversion ===
        # REPLACED: 'Efficiency Ratio' with 'Coefficient of Determination (R^2)'
        # REPLACED: Simple 'Dip Buy' with 'Gaussian Defiance'
        
        # 1. Regime Filter (R-Squared)
        # R^2 measures how well the regression line fits the data.
        # R^2 ~ 1.0 => Strong Trend (Do Not Fade).
        # R^2 ~ 0.0 => Pure Noise/Mean Reversion (Safe to Fade).
        # We strictly enter only when the market is statistically "disorganized" (Low R^2).
        self.max_r2_threshold = 0.25 + (self.dna * 0.1)
        
        # 2. Deviation Threshold (Z-Score)
        # We require a price deviation of ~3.5 to 4.5 standard deviations.
        self.z_entry_threshold = -3.8 - (self.dna * 0.8)
        
        # 3. Crash Protection (Slope)
        # Prevent buying if the regression line itself is angling down too steeply.
        self.min_trend_slope = -0.00025
        
        # === Risk Management ===
        self.take_profit = 0.028   # 2.8% target
        self.stop_loss = 0.075     # 7.5% hard stop
        self.time_stop = 120       # Max hold ticks
        
        self.trade_size_usd = 1800.0
        self.max_positions = 5
        
        # === State ===
        self.history = {}       # {symbol: deque([log_prices])}
        self.positions = {}     # {symbol: {entry, ticks}}
        self.cooldowns = {}     # {symbol: ticks_remaining}

    def on_price_update(self, prices):
        """
        Executed on every tick.
        """
        # 1. Manage Cooldowns
        active_cooldowns = list(self.cooldowns.keys())
        for sym in active_cooldowns:
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Manage Active Positions
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                current_price = float(prices[sym]['priceUsd'])
            except: continue
                
            pos = self.positions[sym]
            pos['ticks'] += 1
            
            pnl_pct = (current_price - pos['entry']) / pos['entry']
            
            # EXIT: Stop Loss
            if pnl_pct <= -self.stop_loss:
                self._close_position(sym, 200) # Long penalty for failure
                continue
                
            # EXIT: Take Profit
            if pnl_pct >= self.take_profit:
                self._close_position(sym, 50) # Short cooloff
                continue
                
            # EXIT: Time Decay
            if pos['ticks'] >= self.time_stop:
                self._close_position(sym, 20)
                continue

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        # Filter universe for liquidity and availability
        candidates = []
        for sym, data in prices.items():
            if sym in self.positions or sym in self.cooldowns:
                continue
            try:
                # Require high liquidity to ensure the statistical model holds (low slippage)
                if float(data.get('liquidity', 0)) >= self.min_liquidity:
                    candidates.append(sym)
            except: continue
            
        # Shuffle to avoid deterministic execution order
        random.shuffle(candidates)
        
        for sym in candidates:
            try:
                raw_price = float(prices[sym]['priceUsd'])
                log_price = math.log(raw_price)
            except: continue
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            
            hist = self.history[sym]
            hist.append(log_price)
            
            if len(hist) < self.window_size:
                continue
            
            # === Statistical Analysis ===
            stats = self._calculate_statistics(hist)
            if not stats:
                continue
                
            z_score, slope, r_squared = stats
            
            # === Alpha Logic Filters ===
            
            # Filter 1: Regime (The Anti-Trend Filter)
            # If R^2 is high, the price is trending strongly. We do NOT fade strong trends.
            if r_squared > self.max_r2_threshold:
                continue
                
            # Filter 2: Macro Trend Safety
            # Do not buy if the baseline is crashing (falling knife protection)
            if slope < self.min_trend_slope:
                continue
                
            # Filter 3: Extreme Deviation
            # Price must be significantly below the regression line
            if z_score < self.z_entry_threshold:
                
                # Filter 4: Momentum Check (Micro-Structure)
                # Check last 3 ticks to ensure we aren't catching a vertically falling knife.
                # We want the acceleration to be slowing down slightly or normal noise.
                if len(hist) > 5:
                    short_term_delta = hist[-1] - hist[-4]
                    # If price dropped > 1.5% in last 4 mins, wait for stabilization
                    if short_term_delta < -0.015:
                        continue

                # Execution
                amount_asset = self.trade_size_usd / raw_price
                
                self.positions[sym] = {
                    'entry': raw_price,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': amount_asset,
                    'reason': ['LOW_R2_REGIME', 'Z_SCORE_DEVIATION']
                }
                
        return None

    def _close_position(self, sym, cooldown_ticks):
        if sym in self.positions:
            del self.positions[sym]
        self.cooldowns[sym] = cooldown_ticks

    def _calculate_statistics(self, data):
        """
        Calculates OLS Linear Regression and R-Squared.
        Returns: (Z-Score, Slope, R-Squared)
        """
        n = len(data)
        if n < 20: return None
        
        y = list(data)
        x = list(range(n))
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*y[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate R-Squared and Standard Deviation
        mean_y = sum_y / n
        ss_tot = sum((val - mean_y) ** 2 for val in y)
        ss_res = 0.0
        
        for i in range(n):
            pred = slope * i + intercept
            res = y[i] - pred
            ss_res += res * res
            
        if ss_tot == 0: return None
        
        r_squared = 1 - (ss_res / ss_tot)
        std_dev = math.sqrt(ss_res / n)
        
        if std_dev < 1e-10: return None
        
        # Z-Score of current price relative to regression
        last_pred = slope * (n - 1) + intercept
        current_resid = y[-1] - last_pred
        z_score = current_resid / std_dev
        
        return z_score, slope, r_squared