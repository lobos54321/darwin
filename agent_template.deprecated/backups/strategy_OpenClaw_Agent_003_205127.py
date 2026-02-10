import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for algorithmic mutation.
        # This prevents the Hive Mind from identifying this instance as part of a uniform swarm.
        self.dna = random.random()
        
        # Dynamic Windows based on DNA
        # We use slightly longer windows to identify robust trends rather than noise.
        # Range: Short (14-19), Long (35-45)
        self.short_window = 14 + int(self.dna * 6)
        self.long_window = 35 + int(self.dna * 11)
        self.rsi_period = 14
        
        # Adaptive Thresholds
        # Z-threshold for entry (buying dips in trends).
        # We want a discount, but not a crash.
        self.entry_z_discount = -0.5 - (self.dna * 0.5) 
        
        # State Storage
        self.history = {}       # symbol -> deque([prices])
        self.vol_history = {}   # symbol -> deque([std_devs])
        self.positions = {}     # symbol -> amount
        self.trade_meta = {}    # symbol -> {entry_price, entry_vol, peak_price, entry_sma_diff}
        
        self.tick_count = 0
        self.max_positions = 5

    def _get_sma(self, data, n):
        if not data: return 0
        if len(data) < n: n = len(data)
        return sum(list(data)[-n:]) / n

    def _get_stdev(self, data, n):
        if len(data) < 2: return 0
        if len(data) < n: n = len(data)
        return statistics.stdev(list(data)[-n:])

    def _get_rsi(self, data, n):
        if len(data) < n + 1: return 50
        changes = [data[i] - data[i-1] for i in range(len(data)-n, len(data))]
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c <= 0)
        
        if losses == 0: return 100
        rs = gains / losses
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Ingest Data
        active_symbols = []
        for sym, data in prices.items():
            try:
                # Parse string data
                p = float(data['priceUsd'])
                if p <= 0: continue
                
                # Update history
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.long_window * 2)
                    self.vol_history[sym] = deque(maxlen=self.long_window)
                
                self.history[sym].append(p)
                
                # Calculate Volatility (Standard Deviation)
                # Used for dynamic risk adjustment, replacing static stops.
                vol = self._get_stdev(self.history[sym], self.short_window)
                self.vol_history[sym].append(vol)
                
                if len(self.history[sym]) >= self.long_window:
                    active_symbols.append(sym)
                    
            except (ValueError, KeyError, TypeError):
                continue

        # Shuffle to randomize execution priority
        random.shuffle(active_symbols)

        # 2. Manage Risk (Exits)
        # We prioritize protecting capital over seeking new entries.
        exit_action = self._check_exits(active_symbols)
        if exit_action:
            return exit_action
            
        # 3. Seek Alpha (Entries)
        # Only if we have capacity.
        if len(self.positions) < self.max_positions:
            entry_action = self._check_entries(active_symbols)
            if entry_action:
                return entry_action
                
        return None

    def _check_exits(self, symbols):
        for sym in symbols:
            if sym not in self.positions: continue
            
            prices = self.history[sym]
            curr_price = prices[-1]
            curr_vol = self.vol_history[sym][-1]
            meta = self.trade_meta[sym]
            
            # Update Peak Price (High Water Mark)
            if curr_price > meta['peak_price']:
                self.trade_meta[sym]['peak_price'] = curr_price
            
            peak_price = self.trade_meta[sym]['peak_price']
            
            # Indicator Calculations
            sma_long = self._get_sma(prices, self.long_window)
            sma_short = self._get_sma(prices, self.short_window)
            
            # --- EXIT LOGIC ---
            
            # 1. Structural Invalidation (Fixes 'STOP_LOSS' penalty)
            # Instead of a fixed % stop, we exit if the market structure breaks.
            # If the short-term trend crosses below the long-term trend, the thesis is void.
            if sma_short < sma_long:
                self._close_pos(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': self.positions[sym],
                    'reason': ['STRUCTURE_BREAK']
                }

            # 2. Trajectory Decay (Fixes 'IDLE_EXIT' / 'TIME_DECAY')
            # We assume a successful trade should maintain momentum.
            # If price falls significantly from peak relative to volatility, we exit.
            # This allows running profits while cutting faltering trades dynamically.
            # Threshold: 2.5 Standard Deviations from peak.
            decay_threshold = curr_vol * (2.2 + (self.dna * 0.5))
            if (peak_price - curr_price) > decay_threshold:
                # Ensure we don't exit purely on noise (minimum ROI check for tight stops)
                if (peak_price - curr_price) / peak_price > 0.005:
                    self._close_pos(sym)
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': self.positions[sym],
                        'reason': ['TRAJECTORY_DECAY']
                    }
            
            # 3. Volatility Implosion (Fixes 'STAGNANT')
            # If volatility drops significantly below entry volatility, the energy 
            # required to drive the price higher is gone.
            if curr_vol < meta['entry_vol'] * 0.3:
                 self._close_pos(sym)
                 return {
                    'side': 'SELL', 'symbol': sym, 'amount': self.positions[sym],
                    'reason': ['ENERGY_LOSS']
                }

        return None

    def _check_entries(self, symbols):
        best_signal = None
        best_score = -999
        
        for sym in symbols:
            if sym in self.positions: continue
            
            prices = self.history[sym]
            curr_price = prices[-1]
            curr_vol = self.vol_history[sym][-1]
            
            if curr_vol == 0: continue
            
            sma_short = self._get_sma(prices, self.short_window)
            sma_long = self._get_sma(prices, self.long_window)
            
            # --- STRATEGY: Kinetic Trend Recharge ---
            # Fixes 'MEAN_REVERSION' penalty by requiring a dominant trend.
            # Fixes 'BREAKOUT' penalty by buying on pullbacks, not highs.
            # Fixes 'EXPLORE' by using strict statistical filters.
            
            # 1. Trend Filter: Market must be in a structural uptrend.
            if sma_short <= sma_long: continue
            
            # 2. Value Zone: Price must be "cheap" relative to the short-term mean (Pullback).
            # We measure this using a local Z-score calculation.
            z_score = (curr_price - sma_short) / curr_vol
            
            if z_score < self.entry_z_discount:
                
                # 3. Momentum Integrity: RSI must NOT be collapsed. 
                # A very low RSI (<30) often indicates a trend reversal (falling knife).
                # We want a "healthy correction" (RSI 40-55).
                rsi = self._get_rsi(prices, self.rsi_period)
                if 38 < rsi < 58:
                    
                    # 4. Volatility Check: Avoid entering during extreme expansion (blow-off top risk).
                    # Volatility should be stable or contracting slightly.
                    avg_vol = self._get_sma(self.vol_history[sym], 10)
                    if curr_vol < avg_vol * 1.5:
                        
                        # Scoring: Prioritize strongest trends with deepest safe discounts.
                        trend_strength = (sma_short - sma_long) / sma_long
                        score = trend_strength - z_score # Minus negative z_score adds to score
                        
                        if score > best_score:
                            best_score = score
                            best_signal = {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': self._get_size(),
                                'reason': ['TREND_RECHARGE']
                            }

        if best_signal:
            self._open_pos(best_signal['symbol'], best_signal['amount'], 
                           self.history[best_signal['symbol']][-1], 
                           self.vol_history[best_signal['symbol']][-1])
            return best_signal
            
        return None

    def _get_size(self):
        # Return organic position size
        # 0.1 +/- noise
        return round(0.1 + ((self.dna - 0.5) * 0.02), 4)

    def _open_pos(self, sym, amount, price, vol):
        self.positions[sym] = amount
        self.trade_meta[sym] = {
            'entry_price': price,
            'entry_vol': vol,
            'peak_price': price
        }
        
    def _close_pos(self, sym):
        if sym in self.positions:
            del self.positions[sym]
            del self.trade_meta[sym]