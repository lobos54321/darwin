import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy DNA ---
        # "Antigravity_V12_Flux_Capacitor"
        # Mutation: Addresses DIP_BUY/KELTNER penalties by enforcing a strict 
        # "Velocity Floor" and "Volatility Gate". We only catch knives that 
        # have statistically decelerated (The Hook).
        # Adjusted parameters for higher precision.
        self.dna = "Antigravity_V12_Flux_Capacitor"
        
        # --- Configuration ---
        self.lookback = 50           # Window for mean/stdev calculation
        self.min_history = 35        # Min ticks before trading
        
        # --- Penalized Logic Fixes ---
        
        # 1. Fix for 'OVERSOLD':
        # Stricter RSI limit. Standard 30 is too noisy and traps algos.
        # Lowered to 21.0 for deep capitulation entries.
        self.rsi_period = 14
        self.rsi_limit = 21.0        
        
        # 2. Fix for 'DIP_BUY' & 'KELTNER':
        # Z-Score Bands: 
        # Reject z < -4.5 (Black Swans/Terra-Luna events).
        # Reject z > -2.3 (Normal noise/insufficient discount).
        self.z_min = -4.5
        self.z_max = -2.3
        
        # 3. Volatility Gate:
        # Reject assets that are too stagnant (low variance) or too chaotic.
        self.min_coeff_var = 0.0006  # 0.06%
        self.max_coeff_var = 0.06    # 6%
        
        # 4. The Hook (Velocity Filter):
        # We ensure the price drop is not accelerating.
        # Max down velocity ensures we don't buy during a vertical cliff.
        self.slope_window = 5        # Faster reaction time
        self.max_down_velocity = -0.0008 
        
        # Liquidity & Volume Gates
        self.min_liquidity = 3_000_000.0
        self.min_vol_24h = 1_000_000.0
        
        # Risk Management
        self.max_positions = 5
        self.position_size = 1.0
        self.stop_loss = 0.048       # 4.8% Stop (Wider to survive wicks)
        self.take_profit = 0.035     # 3.5% Target
        self.hold_timeout = 50       # Ticks (Slightly longer hold)
        self.cooldown_ticks = 20     # Cooldown after exit
        
        # State
        self.history = {}            # {symbol: deque([prices...])}
        self.positions = {}          # {symbol: {entry, tick, amount}}
        self.cooldowns = {}          # {symbol: expire_tick}
        self.tick = 0

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Cooldown Management
        # Remove expired cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick >= t]
        for s in expired:
            del self.cooldowns[s]
            
        # 2. Position Management
        # Check active positions for SL/TP/Timeout
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

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        # Randomize scan order to avoid deterministic bias
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
            
            # Liquidity Filter
            if liq < self.min_liquidity or vol < self.min_vol_24h: continue
            
            # History Maintenance
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.min_history: continue
            
            # --- SIGNAL CALCULATION ---
            series = list(self.history[sym])
            
            # A. Statistical Baseline
            mean_p = statistics.mean(series)
            stdev_p = statistics.stdev(series) if len(series) > 1 else 0
            
            if mean_p == 0 or stdev_p == 0: continue
            
            # B. Volatility Check (Anti-Chopping)
            coeff_var = stdev_p / mean_p
            if not (self.min_coeff_var <= coeff_var <= self.max_coeff_var): continue
            
            # C. Z-Score Filter (Deep Dip)
            # Calculates how many deviations away from mean we are.
            z_score = (price - mean_p) / stdev_p
            if not (self.z_min <= z_score <= self.z_max): continue
            
            # D. RSI Filter (Momentum)
            rsi = self._calc_rsi(series, self.rsi_period)
            if rsi > self.rsi_limit: continue
            
            # E. The Hook (Velocity Filter)
            # Calculates the linear slope of the most recent ticks.
            recent_slice = series[-self.slope_window:]
            slope = self._calc_slope(recent_slice)
            norm_slope = slope / price
            
            # If slope is too steep negative, wait.
            if norm_slope < self.max_down_velocity: continue
            
            # Valid Entry
            self.positions[sym] = {
                'entry': price,
                'tick': self.tick,
                'amount': self.position_size
            }
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.position_size,
                'reason': [f'Z:{z_score:.2f}', f'RSI:{rsi:.1f}']
            }
            
        return None

    # --- MATH HELPERS ---

    def _calc_rsi(self, data, period):
        if len(data) < period + 1: return 50.0
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