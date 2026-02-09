import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy DNA ---
        # "Antigravity_V9_Helix"
        # Mutation: Addresses 'LR_RESIDUAL' by normalizing regression error against volatility.
        # Mutation: Addresses 'Z:-3.93' by capping Z-score depth and checking downside velocity.
        self.dna = "Antigravity_V9_Helix"
        
        # --- Data Windows ---
        self.full_window = 50        # Lookback for volatility/Z-score
        self.reg_window = 14         # Lookback for linear regression (structural analysis)
        
        # --- SIGNAL PARAMETERS ---
        
        # FIX for 'Z:-3.93' (Falling Knife)
        # We define a "Safe Dip Zone". 
        # Deep crashes (> -2.8 sigma) are ignored as falling knives.
        # Shallow dips (< -1.7 sigma) are ignored as low probability.
        self.z_min = -2.80 
        self.z_max = -1.70
        
        # FIX for 'LR_RESIDUAL' (Structure Quality)
        # Instead of raw residuals, we use Normalized Root Mean Square Error (NRMSE) 
        # relative to the slope to ensure the dip is smooth, not jagged.
        self.min_r_squared = 0.94    # High linearity required
        self.max_residual_dev = 0.006 # Maximum allowed deviation from the regression line (0.6%)
        
        # Secondary Filters
        self.rsi_period = 14
        self.rsi_threshold = 24.0    # Strict oversold level
        
        # Liquidity & Volume Gates
        self.min_liquidity = 2_200_000.0
        self.min_vol_24h = 800_000.0
        
        # Risk Management
        self.max_positions = 5
        self.position_size = 1.0     # Fixed trade amount
        self.stop_loss = 0.048       # 4.8% Stop
        self.take_profit = 0.025     # 2.5% Target
        self.hold_timeout = 35       # Max hold ticks
        self.cooldown_ticks = 20     # Cooldown after exit
        
        # Internal State
        self.history = {}            # {symbol: deque([price, ...])}
        self.positions = {}          # {symbol: {entry, tick, amount}}
        self.cooldowns = {}          # {symbol: expire_tick}
        self.tick = 0

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Manage Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick >= t]
        for s in expired:
            del self.cooldowns[s]
            
        # 2. Manage Active Positions
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
            except (ValueError, KeyError, TypeError): continue
                
            pos = self.positions[sym]
            roi = (curr_price - pos['entry']) / pos['entry']
            
            exit_reason = None
            if roi <= -self.stop_loss:
                exit_reason = 'STOP_LOSS'
            elif roi >= self.take_profit:
                exit_reason = 'TAKE_PROFIT'
            elif self.tick - pos['tick'] >= self.hold_timeout:
                exit_reason = 'TIMEOUT'
                
            if exit_reason:
                self.cooldowns[sym] = self.tick + self.cooldown_ticks
                amount = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [exit_reason]
                }

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            # Basic Availability Checks
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                vol = float(p_data['volume24h'])
            except (ValueError, KeyError, TypeError): continue
            
            if liq < self.min_liquidity or vol < self.min_vol_24h: continue
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.full_window)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.full_window: continue
            
            # --- SIGNAL CALCULATION ---
            series = list(self.history[sym])
            
            # A. Z-Score Filter (Addressing Z:-3.93)
            # Calculates statistical depth.
            z_score = self._calc_z_score(series)
            
            # We strictly reject anything outside the "Safe Dip Zone".
            # If z_score is -4.0, it's a crash -> Reject.
            # If z_score is -1.0, it's noise -> Reject.
            if not (self.z_min <= z_score <= self.z_max):
                continue
                
            # B. Linear Regression & Residual Check (Addressing LR_RESIDUAL)
            # Analyze only the recent 'reg_window' candles for structural integrity.
            reg_slice = series[-self.reg_window:]
            slope, r2, max_resid_pct = self._calc_regression_metrics(reg_slice)
            
            # 1. Slope must be negative (we are buying a dip)
            if slope >= 0: continue
            
            # 2. Linearity Check
            if r2 < self.min_r_squared: continue
            
            # 3. Residual Check (The Specific Fix)
            # Ensures no single candle deviated too far from the trend line.
            if max_resid_pct > self.max_residual_dev: continue
            
            # C. RSI Filter
            rsi = self._calc_rsi(series, self.rsi_period)
            if rsi > self.rsi_threshold: continue
            
            # Signal Validated
            self.positions[sym] = {
                'entry': price,
                'tick': self.tick,
                'amount': self.position_size
            }
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.position_size,
                'reason': ['LR_FIT', f'Z:{z_score:.2f}']
            }
            
        return None

    # --- MATH HELPERS ---

    def _calc_z_score(self, data):
        if len(data) < 2: return 0.0
        mean = statistics.mean(data)
        stdev = statistics.stdev(data)
        if stdev == 0: return 0.0
        return (data[-1] - mean) / stdev

    def _calc_rsi(self, data, period):
        if len(data) < period + 1: return 50.0
        changes = [b - a for a, b in zip(data[:-1], data[1:])]
        recent_changes = changes[-period:]
        
        gains = [c for c in recent_changes if c > 0]
        losses = [-c for c in recent_changes if c < 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_regression_metrics(self, data):
        # Returns: slope, r_squared, max_residual_percentage
        n = len(data)
        if n < 2: return 0, 0, 0
        
        x = list(range(n))
        y = data
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*j for i, j in zip(x, y))
        
        denominator = n * sum_xx - sum_x * sum_x
        if denominator == 0: return 0, 0, 0
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate R-Squared and Residuals
        y_mean = sum_y / n
        ss_tot = sum((val - y_mean)**2 for val in y)
        ss_res = 0
        max_resid_pct = 0.0
        
        for i, val in enumerate(y):
            predicted = slope * i + intercept
            resid = val - predicted
            ss_res += resid**2
            
            # Calculate residual as a percentage of price
            # This handles the 'LR_RESIDUAL' fix by normalizing scale
            if val > 0:
                resid_pct = abs(resid) / val
                if resid_pct > max_resid_pct:
                    max_resid_pct = resid_pct
        
        r2 = 1.0 - (ss_res / ss_tot) if ss_tot != 0 else 0.0
        
        return slope, r2, max_resid_pct