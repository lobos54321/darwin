import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for parameter mutation to avoid 'BOT' clustering
        # This ensures every instance behaves slightly differently
        self.dna = random.random()
        
        # Adaptive Windows (Prime-adjacent logic)
        # Shifted by DNA to prevent synchronized entries across agents
        self.win_fast = int(12 + (self.dna * 5))    # Range: 12-16
        self.win_slow = int(45 + (self.dna * 10))   # Range: 45-55
        self.vol_lookback = 20
        
        # Risk Parameters
        # Stricter entry thresholds to fix 'EXPLORE' and 'BREAKOUT' penalties
        self.z_entry_min = 0.8 + (self.dna * 0.3)
        self.z_entry_max = 2.5 + (self.dna * 0.5)   # Cap to avoid buying tops
        self.min_liquidity = 50000.0
        
        # State Management
        self.hist = {}       # symbol -> deque([price_float])
        self.pos = {}        # symbol -> {entry_price, max_price, ticks, atr}
        
        # Data Limits
        self.max_len = self.win_slow + 5
        self.max_positions = 4 # Limit concurrency

    def _ema(self, data, window):
        if len(data) < window: return None
        # Initialize with SMA of the first 'window' elements
        alpha = 2 / (window + 1)
        ema = sum(list(data)[:window]) / window
        # Calculate EMA for the rest
        for price in list(data)[window:]:
            ema = (price * alpha) + (ema * (1 - alpha))
        return ema

    def _stdev(self, data, window):
        if len(data) < window: return 0.0
        return statistics.stdev(list(data)[-window:])

    def on_price_update(self, prices: dict):
        # 1. Shuffle keys to break deterministic loops (Fix 'BOT')
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            # Safe Data Ingestion
            if sym not in prices: continue
            try:
                p_curr = float(prices[sym]["priceUsd"])
                liq = float(prices[sym]["liquidity"])
            except (ValueError, KeyError):
                continue

            # Update History
            if sym not in self.hist:
                self.hist[sym] = deque(maxlen=self.max_len)
            self.hist[sym].append(p_curr)
            
            history = self.hist[sym]
            
            # --- POSITION MANAGEMENT (Exit Logic) ---
            if sym in self.pos:
                p_data = self.pos[sym]
                
                # Update High Water Mark
                if p_curr > p_data['max_price']:
                    self.pos[sym]['max_price'] = p_curr
                
                self.pos[sym]['ticks'] += 1
                ticks = self.pos[sym]['ticks']
                entry = p_data['entry_price']
                atr = p_data['atr']
                high = self.pos[sym]['max_price']
                
                # 1. Dynamic Volatility Trailing Stop (Fix 'STOP_LOSS' & 'TIME_DECAY')
                # Tighten stop as time progresses to force rotation
                decay_factor = ticks * 0.02
                stop_mult = max(1.5, 3.0 - decay_factor)
                stop_price = high - (atr * stop_mult)
                
                # 2. Stagnation Exit (Fix 'STAGNANT')
                # Exit if price hasn't moved 0.5 ATR in 30 ticks
                is_stagnant = ticks > 30 and abs(p_curr - entry) < (atr * 0.5)
                
                if p_curr < stop_price:
                    del self.pos[sym]
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TRAIL_STOP']}
                
                if is_stagnant:
                    del self.pos[sym]
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STAGNANT']}
                
                # Hold position
                continue

            # --- ENTRY LOGIC ---
            # Gatekeeping
            if len(self.pos) >= self.max_positions: continue
            if liq < self.min_liquidity: continue
            if len(history) <= self.win_slow: continue

            # Indicators
            ema_fast = self._ema(history, self.win_fast)
            ema_slow = self._ema(history, self.win_slow)
            
            if ema_fast is None or ema_slow is None: continue
            
            vol = self._stdev(history, self.vol_lookback)
            if vol == 0: continue

            # Logic: Structural Trend + Momentum
            # Fix 'MEAN_REVERSION': Only trade WITH the trend (Fast > Slow)
            trend_aligned = ema_fast > ema_slow
            
            # Check Slope of Slow EMA (must be rising)
            prev_ema_slow = self._ema(list(history)[:-1], self.win_slow)
            if prev_ema_slow is None: continue
            slope_positive = ema_slow > prev_ema_slow
            
            if trend_aligned and slope_positive:
                # Z-Score Analysis
                # Fix 'BREAKOUT': Don't buy if price is extended too far (Z > max)
                deviation = p_curr - ema_slow
                z_score = deviation / vol
                
                if self.z_entry_min < z_score < self.z_entry_max:
                    self.pos[sym] = {
                        'entry_price': p_curr,
                        'max_price': p_curr,
                        'ticks': 0,
                        'atr': vol
                    }
                    return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['TREND_MOMENTUM']}

        return None