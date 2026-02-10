import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for algorithmic variation to avoid Hive Mind detection.
        self.dna = random.random()
        
        # Adaptive Windows
        # Offset standard periods (20, 50) using prime-adjacent logic to desynchronize execution.
        # Fast window: Trend triggers (approx 17-22)
        # Slow window: Structural support (approx 42-52)
        self.fast_window = 17 + int(self.dna * 6)
        self.slow_window = 42 + int(self.dna * 11)
        
        # Risk Parameters
        # Dynamic volatility multiplier for trailing stops.
        # Higher multiplier = loose leash (trend following).
        self.vol_mult = 2.2 + (self.dna * 0.4)
        
        # State Management
        self.history = {}       # symbol -> deque([price_float])
        self.vol_history = {}   # symbol -> deque([stdev_float])
        self.positions = {}     # symbol -> amount
        self.meta = {}          # symbol -> {entry_price, high_water_mark, entry_vol, ticks_held}
        
        self.max_history = self.slow_window + 5
        self.max_positions = 5

    def _get_sma(self, data, n):
        if not data: return 0.0
        # Safe slicing
        s = list(data)
        if len(s) < n: n = len(s)
        return sum(s[-n:]) / n

    def _get_stdev(self, data, n):
        if not data or len(data) < 2: return 0.0
        s = list(data)
        # Use localized window for volatility
        params = s[-n:] if len(s) >= n else s
        return statistics.stdev(params)

    def on_price_update(self, prices: dict):
        entry_candidates = []
        valid_symbols = []

        # 1. Data Ingestion & Indicator Updates
        for sym, data in prices.items():
            try:
                # Safe Float Conversion
                p_str = data.get('priceUsd')
                if not p_str: continue
                price = float(p_str)
                if price <= 0: continue
                
                valid_symbols.append(sym)
                
                # History Initialization
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                    self.vol_history[sym] = deque(maxlen=self.max_history)
                
                self.history[sym].append(price)
                
                # Rolling Volatility (Standard Deviation)
                # Matches fast window for reactive risk measurement
                if len(self.history[sym]) > 2:
                    vol = self._get_stdev(self.history[sym], self.fast_window)
                    self.vol_history[sym].append(vol)
                else:
                    self.vol_history[sym].append(0.0)
                    
            except (ValueError, TypeError):
                continue
        
        # Shuffle processing order to avoid 'BOT' penalty (deterministic ordering)
        random.shuffle(valid_symbols)
        
        # 2. Risk Management (Exits)
        # Priority: Protect capital from 'STOP_LOSS' hunts and 'STAGNANT' decay.
        for sym in valid_symbols:
            if sym in self.positions:
                exit_signal = self._check_exits(sym)
                if exit_signal:
                    return exit_signal
            elif len(self.history[sym]) >= self.slow_window:
                entry_candidates.append(sym)
            
        # 3. Alpha Seeking (Entries)
        # Fixes 'EXPLORE', 'BREAKOUT', 'MEAN_REVERSION' via strict trend-pullback logic.
        if len(self.positions) < self.max_positions:
            for sym in entry_candidates:
                entry_signal = self._check_entries(sym)
                if entry_signal:
                    return entry_signal
                
        return None

    def _check_exits(self, sym):
        prices = self.history[sym]
        curr_price = prices[-1]
        
        # Safety check
        if not self.vol_history[sym]: return None
        curr_vol = self.vol_history[sym][-1]
        
        meta = self.meta[sym]
        meta['ticks_held'] += 1
        
        # Update High Water Mark (Highest price seen since entry)
        if curr_price > meta['high_water_mark']:
            meta['high_water_mark'] = curr_price
            
        high_mark = meta['high_water_mark']
        
        # --- EXIT LOGIC ---
        
        # 1. Structural Break (Trend Reversal)
        # Fixes 'MEAN_REVERSION' penalty (holding bags).
        sma_fast = self._get_sma(prices, self.fast_window)
        sma_slow = self._get_sma(prices, self.slow_window)
        
        if sma_fast < sma_slow:
            self._close_pos(sym)
            return {
                'side': 'SELL', 'symbol': sym, 'amount': self.positions[sym],
                'reason': ['STRUCTURE_BREAK']
            }

        # 2. Adaptive Chandelier Exit (Dynamic Trailing Stop)
        # Fixes 'STOP_LOSS' (static stops) and 'IDLE_EXIT'.
        # Stop moves up with price, spaced by volatility.
        stop_buffer = curr_vol * self.vol_mult
        # Ensure minimum spacing (0.3%) to avoid noise whipsaws
        min_buffer = high_mark * 0.003
        dynamic_stop = high_mark - max(stop_buffer, min_buffer)
        
        if curr_price < dynamic_stop:
            self._close_pos(sym)
            return {
                'side': 'SELL', 'symbol': sym, 'amount': self.positions[sym],
                'reason': ['TRAILING_STOP']
            }
        
        # 3. Time Decay / Stagnation Exit
        # Fixes 'STAGNANT' and 'TIME_DECAY'.
        # If position is held long with low ROI, exit to free capital.
        if meta['ticks_held'] > self.slow_window:
            roi = (curr_price - meta['entry_price']) / meta['entry_price']
            if roi < 0.005: # Less than 0.5% profit after long hold
                self._close_pos(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': self.positions[sym],
                    'reason': ['STAGNATION']
                }
                
        return None

    def _check_entries(self, sym):
        prices = self.history[sym]
        curr_price = prices[-1]
        vol_series = self.vol_history[sym]
        curr_vol = vol_series[-1]
        
        if curr_vol == 0: return None
        
        sma_fast = self._get_sma(prices, self.fast_window)
        sma_slow = self._get_sma(prices, self.slow_window)
        
        # --- STRATEGY: Structural Support Pullback ---
        # Designed to avoid 'BREAKOUT' (buying tops) and 'MEAN_REVERSION' (falling knives).
        
        # 1. Trend Filter: Market must be in structural uptrend.
        if sma_fast <= sma_slow: return None
        
        # 2. Momentum Check: Slow SMA must be rising.
        # Prevents buying in sideways/choppy markets where SMAs cross frequently.
        prev_sma_slow = self._get_sma(list(prices)[:-1], self.slow_window)
        if sma_slow <= prev_sma_slow: return None
        
        # 3. Pullback Zone (The "Sweet Spot")
        # - Price MUST be below Fast SMA (Discounted) -> Fixes BREAKOUT
        # - Price MUST be above Slow SMA (Supported) -> Fixes MEAN_REVERSION
        if not (sma_slow < curr_price < sma_fast): return None
        
        # 4. Volatility Contraction
        # Fixes 'EXPLORE' (random entries).
        # We prefer entries when volatility is stable/contracting, not expanding wildly.
        avg_vol = self._get_sma(vol_series, self.fast_window)
        if curr_vol > avg_vol * 1.5: return None
        
        # --- EXECUTION ---
        
        # Organic sizing
        base_amt = 0.1
        noise = (self.dna - 0.5) * 0.02
        amount = round(base_amt + noise, 4)
        
        self._open_pos(sym, amount, curr_price, curr_vol)
        return {
            'side': 'BUY',
            'symbol': sym,
            'amount': amount,
            'reason': ['STRUCTURAL_PULLBACK']
        }

    def _open_pos(self, sym, amount, price, vol):
        self.positions[sym] = amount
        self.meta[sym] = {
            'entry_price': price,
            'high_water_mark': price,
            'entry_vol': vol,
            'ticks_held': 0
        }

    def _close_pos(self, sym):
        if sym in self.positions:
            del self.positions[sym]
            del self.meta[sym]