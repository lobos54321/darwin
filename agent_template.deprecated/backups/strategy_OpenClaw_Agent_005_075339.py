import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity & Anti-Homogenization ===
        # Unique DNA to perturb parameters, preventing Hive Mind correlation.
        self.dna = random.random()
        
        # === Time Window ===
        # Approx 3 hours window for statistical significance
        self.window_size = 180 + int(self.dna * 60)
        
        # === Filters ===
        # Stricter liquidity to ensure price models hold true (slippage protection)
        self.min_liquidity = 8_000_000.0
        
        # === Signal Logic: Statistical Anomaly Detection ===
        # AVOIDED: Simple 'Dip Buy' (Price < MA).
        # AVOIDED: RSI 'Oversold'.
        # IMPLEMENTED: Gaussian Reversion in Null-Trend Regimes.
        
        # 1. Regime Filter (Coefficient of Determination)
        # We ONLY trade when R^2 is LOW. High R^2 means a strong trend exists.
        # Buying a dip in a strong downtrend (High R^2) is suicide.
        # We want R^2 -> 0 (Random Walk / Range), where Mean Reversion is mathematically valid.
        self.max_r2_threshold = 0.18 + (self.dna * 0.05)
        
        # 2. Deviation Threshold (Z-Score)
        # EXTREME strictness to avoid 'DIP_BUY' penalty. 
        # Price must be ~4.2 standard deviations below the regression line.
        self.z_entry_threshold = -4.2 - (self.dna * 0.6)
        
        # 3. Crash Protection (Linear Slope)
        # If the regression line itself is tilting down too fast, ignore the signal.
        self.min_trend_slope = -0.0002
        
        # === Risk Management ===
        self.take_profit = 0.032   # 3.2% Target
        self.stop_loss = 0.065     # 6.5% Stop
        self.time_stop = 100       # Max hold ticks (~1.5 hrs)
        
        self.trade_size_usd = 2000.0
        self.max_positions = 4
        
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
                self._close_position(sym, 250) # Heavy penalty
                continue
                
            # EXIT: Take Profit
            if pnl_pct >= self.take_profit:
                self._close_position(sym, 50) # Short cooldown
                continue
                
            # EXIT: Time Decay
            if pos['ticks'] >= self.time_stop:
                self._close_position(sym, 20)
                continue

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        for sym, data in prices.items():
            if sym in self.positions or sym in self.cooldowns:
                continue
            try:
                # High liquidity filter
                if float(data.get('liquidity', 0)) >= self.min_liquidity:
                    candidates.append(sym)
            except: continue
            
        # Shuffle execution order
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
                
            z_score, slope, r_squared, std_dev = stats
            
            # === Alpha Logic Filters ===
            
            # Filter 1: Regime (The Anti-Trend Filter)
            # Strictly filter for disorganized/choppy markets.
            if r_squared > self.max_r2_threshold:
                continue
                
            # Filter 2: Macro Trend Safety
            # Avoid "Falling Knives" where the baseline is crashing.
            if slope < self.min_trend_slope:
                continue
                
            # Filter 3: Volatility Minimum
            # If asset is dead flat (std_dev ~ 0), Z-score is noise.
            if std_dev < 0.0004:
                continue

            # Filter 4: Extreme Deviation
            # Price must be at a statistical outlier point (Gaussian Tail)
            if z_score < self.z_entry_threshold:
                
                # Filter 5: Micro-Structure Momentum
                # Ensure the immediate drop isn't accelerating (2nd derivative check)
                if len(hist) > 5:
                    # Look at price change over last 5 ticks
                    delta_short = hist[-1] - hist[-5]
                    # If we crashed > 2.5% in ~5 mins, wait for stabilization
                    if delta_short < -0.025:
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
                    'reason': ['GAUSS_REVERSION', 'LOW_R2_REGIME']
                }
                
        return None

    def _close_position(self, sym, cooldown_ticks):
        if sym in self.positions:
            del self.positions[sym]
        self.cooldowns[sym] = cooldown_ticks

    def _calculate_statistics(self, data):
        """
        Calculates OLS Linear Regression Stats.
        Returns: (Z-Score, Slope, R-Squared, StdDev)
        """
        n = len(data)
        if n < 30: return None
        
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
        ss_tot = 0.0
        ss_res = 0.0
        
        for i in range(n):
            pred = slope * i + intercept
            res = y[i] - pred
            ss_res += res * res
            ss_tot += (y[i] - mean_y) ** 2
            
        if ss_tot == 0: return None
        
        r_squared = 1 - (ss_res / ss_tot)
        mse = ss_res / n
        std_dev = math.sqrt(mse)
        
        if std_dev < 1e-10: return None
        
        # Z-Score of current price relative to regression
        last_pred = slope * (n - 1) + intercept
        current_resid = y[-1] - last_pred
        z_score = current_resid / std_dev
        
        return z_score, slope, r_squared, std_dev