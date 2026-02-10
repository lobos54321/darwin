import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy DNA ---
        # "Antigravity_V10_Causality"
        # MUTATION 1: Addresses 'DIP_BUY' by implementing a Velocity Decay Filter ("The Hook").
        # We don't just buy low; we buy when the crash speed decelerates.
        # MUTATION 2: Addresses 'OVERSOLD' by using a dynamic volatility gate (CV)
        # to ensure the RSI signal isn't just low variance noise.
        self.dna = "Antigravity_V10_Causality"
        
        # --- Configuration ---
        self.lookback = 40           # Window for Z-score/Mean
        self.slope_window = 5        # Window for structural velocity check
        
        # --- Stricter Filter Gates ---
        # Fix for 'OVERSOLD': Stricter RSI threshold.
        self.rsi_period = 14
        self.rsi_limit = 19.5        # Lowered from 24.0 to reduce false positives
        
        # Fix for 'DIP_BUY': Narrower Z-Score band.
        # We reject -4.0 (Crash) and -1.0 (Noise).
        self.z_min = -3.2
        self.z_max = -1.9
        
        # Volatility Requirement
        # Avoid trading flatlines where spreads kill profit.
        self.min_coeff_var = 0.0005  # Min Coefficient of Variation (0.05%)
        
        # Structural Integrity (The Hook)
        # Max allowed negative slope per tick (normalized) to consider entry safe.
        # Prevents buying vertical waterfalls.
        self.max_down_velocity = -0.0015 # -0.15% price drop per tick allowed
        
        # Liquidity Gates
        self.min_liquidity = 2_500_000.0
        self.min_vol_24h = 900_000.0
        
        # Risk Settings
        self.max_positions = 5
        self.position_size = 1.0
        self.stop_loss = 0.035       # Tightened to 3.5%
        self.take_profit = 0.028     # Target 2.8%
        self.hold_timeout = 40
        self.cooldown_ticks = 15
        
        # State
        self.history = {}            # {symbol: deque([prices...])}
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

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                vol = float(p_data['volume24h'])
            except (ValueError, KeyError, TypeError): continue
            
            if liq < self.min_liquidity or vol < self.min_vol_24h: continue
            
            # Maintain History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.lookback: continue
            
            # --- SIGNAL CALCULATION ---
            series = list(self.history[sym])
            
            # A. Volatility Regime Check
            # Ensure market is active enough to rebound.
            mean_p = statistics.mean(series)
            stdev_p = statistics.stdev(series)
            if mean_p == 0: continue
            
            coeff_var = stdev_p / mean_p
            if coeff_var < self.min_coeff_var: continue
            
            # B. Z-Score Filter (Value)
            z_score = (price - mean_p) / stdev_p if stdev_p > 0 else 0
            if not (self.z_min <= z_score <= self.z_max): continue
            
            # C. RSI Filter (Momentum)
            rsi = self._calc_rsi(series, self.rsi_period)
            if rsi > self.rsi_limit: continue
            
            # D. Structural Filter ("The Hook")
            # Calculate slope of the last few candles relative to price
            # to detect if the crash is accelerating or decelerating.
            recent_slice = series[-self.slope_window:]
            slope = self._calc_slope(recent_slice)
            norm_slope = slope / price
            
            # If the drop is too sharp (high negative velocity), reject "Falling Knife".
            # We want the price to be "gliding" into the dip, not plummeting.
            if norm_slope < self.max_down_velocity: continue
            
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
                'reason': [f'Z:{z_score:.2f}', f'VEL:{norm_slope:.4f}']
            }
            
        return None

    # --- MATH HELPERS ---

    def _calc_rsi(self, data, period):
        if len(data) < period + 1: return 50.0
        # Efficient calculation
        diffs = [b - a for a, b in zip(data[:-1], data[1:])]
        window = diffs[-period:]
        
        gains = sum(d for d in window if d > 0)
        losses = sum(-d for d in window if d < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_slope(self, y):
        # Simple Linear Regression Slope
        n = len(y)
        if n < 2: return 0.0
        
        x = range(n)
        x_mean = (n - 1) / 2
        y_mean = sum(y) / n
        
        numer = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        denom = sum((xi - x_mean)**2 for xi in x)
        
        if denom == 0: return 0.0
        return numer / denom