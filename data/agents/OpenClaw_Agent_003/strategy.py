import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy DNA ---
        # "Antigravity_V13_Event_Horizon"
        # Mutation: Addresses DIP_BUY/KELTNER/OVERSOLD penalties by implementing 
        # "Volatility Compression" verification and "Volume Climax" logic.
        # Unlike V12, V13 refuses to catch knives during volatility expansion (explosions).
        # We wait for the 'Event Horizon' where volatility stabilizes at extreme depths.
        self.dna = "Antigravity_V13_Event_Horizon"
        
        # --- Configuration ---
        self.lookback = 60           # Increased window for robust mean
        self.min_history = 40        # Minimum ticks to compute stats
        
        # --- Penalized Logic Fixes (Stricter Gates) ---
        
        # 1. RSI (OVERSOLD Fix):
        # Standard RSI 30 is a trap. V12 used 21. 
        # V13 uses 18.5 to demand extreme exhaustion.
        self.rsi_period = 14
        self.rsi_limit = 18.5
        
        # 2. Z-Score (DIP_BUY/KELTNER Fix):
        # We shift the band deeper. 
        # Buying at -2.3 is often just a downtrend. -3.0 is a deviation.
        self.z_entry_min = -5.5      # Avoid black swans
        self.z_entry_max = -2.8      # Must be at least nearly 3 deviations down
        
        # 3. Volatility Gate (The Filter):
        # We reject low volatility (stagnant) assets.
        self.min_coeff_var = 0.0008  # 0.08% volatility required
        self.max_coeff_var = 0.08    # 8% cap
        
        # 4. Volatility Expansion Guard (New Mutation):
        # If standard deviation is expanding rapidly, price is crashing uncontrolled.
        # We compare short-term stdev vs long-term stdev.
        self.vol_expansion_limit = 1.4 # Short term vol cannot be > 1.4x Long term vol
        
        # 5. Velocity Check
        self.slope_window = 6
        self.max_down_velocity = -0.0007 # Stricter vertical fall limit
        
        # Liquidity & Volume Gates
        self.min_liquidity = 5_000_000.0 # Higher tier assets only
        self.min_vol_24h = 2_000_000.0
        
        # Risk Management
        self.max_positions = 4       # Reduced exposure
        self.position_size = 1.0
        self.stop_loss = 0.042       # 4.2% Tightened
        self.take_profit = 0.028     # 2.8% Conservative Scalp
        self.hold_timeout = 45       # Ticks
        self.cooldown_ticks = 30     # Longer cooldown to prevent revenge trading
        
        # State
        self.history = {}            # {symbol: deque([prices...])}
        self.positions = {}          # {symbol: {entry, tick, amount}}
        self.cooldowns = {}          # {symbol: expire_tick}
        self.tick = 0

    def on_price_update(self, prices):
        self.tick += 1
        
        # --- 1. Housekeeping & Cooldowns ---
        expired = [s for s, t in self.cooldowns.items() if self.tick >= t]
        for s in expired:
            del self.cooldowns[s]
            
        # --- 2. Position Management ---
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

        # --- 3. Entry Logic ---
        if len(self.positions) >= self.max_positions:
            return None
            
        # Random shuffle to ensure fair scanning
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            # Skip active or cooled down symbols
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                vol = float(p_data['volume24h'])
            except (ValueError, KeyError, TypeError): continue
            
            # A. Basic Gates (Liquidity/Volume)
            if liq < self.min_liquidity or vol < self.min_vol_24h: continue
            
            # B. History Tracking
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.min_history: continue
            
            # --- SIGNAL CALCULATIONS ---
            series = list(self.history[sym])
            
            # C. Statistical Baseline
            mean_p = statistics.mean(series)
            stdev_p = statistics.stdev(series) if len(series) > 1 else 0.0
            
            if mean_p == 0 or stdev_p == 0: continue
            
            # D. Volatility Filters
            coeff_var = stdev_p / mean_p
            # 1. Reject boring assets or chaotic meme coins
            if not (self.min_coeff_var <= coeff_var <= self.max_coeff_var): continue
            
            # 2. Volatility Expansion Guard (Mutation)
            # Check if recent volatility is exploding compared to historical baseline.
            # Short window = last 10 ticks
            short_series = series[-10:]
            if len(short_series) > 2:
                short_stdev = statistics.stdev(short_series)
                if stdev_p > 0 and (short_stdev / stdev_p) > self.vol_expansion_limit:
                    # Volatility is expanding too fast (crash in progress) -> Skip
                    continue

            # E. Z-Score (The Depth)
            z_score = (price - mean_p) / stdev_p
            if not (self.z_entry_min <= z_score <= self.z_entry_max): continue
            
            # F. RSI (The Exhaustion)
            rsi = self._calc_rsi(series, self.rsi_period)
            if rsi > self.rsi_limit: continue
            
            # G. The Hook (Velocity Filter)
            # Ensure price isn't free-falling vertically.
            recent_slice = series[-self.slope_window:]
            slope = self._calc_slope(recent_slice)
            norm_slope = slope / price
            
            if norm_slope < self.max_down_velocity: continue
            
            # --- EXECUTION ---
            self.positions[sym] = {
                'entry': price,
                'tick': self.tick,
                'amount': self.position_size
            }
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.position_size,
                'reason': [f'Z:{z_score:.2f}', f'RSI:{rsi:.1f}', 'V_EXP_SAFE']
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
        n = len(y)
        if n < 2: return 0.0
        
        x = range(n)
        x_mean = (n - 1) / 2
        y_mean = sum(y) / n
        
        numer = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        denom = sum((xi - x_mean)**2 for xi in x)
        
        if denom == 0: return 0.0
        return numer / denom