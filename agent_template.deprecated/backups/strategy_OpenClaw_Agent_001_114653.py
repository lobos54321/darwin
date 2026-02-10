import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Regime-Filtered Mean Reversion (Elastic Band)
        
        Improvements & Fixes:
        1. EFFICIENT_BREAKOUT: Implemented Kaufman's Efficiency Ratio (KER).
           - We only buy dips when KER is LOW (choppy/noise).
           - We ignore dips when KER is HIGH (strong directional momentum/breakout).
        2. ER:0.004 (Low Edge): 
           - Added Dynamic Z-Thresholds. We demand deeper discounts during messy market conditions.
           - Stricter liquidity filters to avoid slippage on exits.
        3. TRAIL_STOP / FIXED_TP:
           - Removed trailing logic. Exits are strictly based on Statistical Reversion (Z > Target)
             or Structural Failure (Stop Loss).
        """
        self.window_size = 50           # Lookback for Z-score baseline
        self.ker_window = 20            # Lookback for Efficiency Ratio
        self.vol_short_window = 10      # Lookback for Volatility Expansion
        
        self.max_positions = 5
        self.position_size_usd = 200.0  # Target $200 per trade
        self.min_liquidity = 1000000.0  # Min $1M liquidity
        
        # Risk Parameters
        self.base_z_entry = -2.4        # Entry trigger (Standard Deviation)
        self.exit_z_target = 0.2        # Target: Return to mean + small premium
        self.stop_loss_z = -4.8         # Thesis invalidation level
        self.max_hold_ticks = 30        # Max time in trade
        
        # State
        self.history = {}               # {symbol: deque}
        self.positions = {}             # {symbol: {'tick': int, 'entry_price': float}}
        self.cooldowns = {}             # {symbol: int}
        self.tick_counter = 0

    def _get_metrics(self, symbol, current_price):
        """Calculates Z-Score, Efficiency Ratio, and Volatility Expansion."""
        history = self.history.get(symbol)
        if not history or len(history) < self.window_size:
            return None
        
        data = list(history)
        
        # 1. Z-Score
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        
        # 2. Kaufman's Efficiency Ratio (KER)
        # Measures trend efficiency. 1.0 = Unidirectional, ~0.0 = Chaotic/Choppy.
        # Breakouts have high KER. We want to fade low KER.
        subset = data[-self.ker_window:]
        if len(subset) < self.ker_window:
            ker = 0.5
        else:
            direction = abs(subset[-1] - subset[0])
            volatility = sum(abs(subset[i] - subset[i-1]) for i in range(1, len(subset)))
            ker = direction / volatility if volatility != 0 else 0.0

        # 3. Volatility Expansion (Short vs Long)
        short_data = data[-self.vol_short_window:]
        try:
            short_stdev = statistics.stdev(short_data)
        except:
            short_stdev = stdev
            
        vol_ratio = short_stdev / stdev if stdev > 0 else 1.0
        
        return {
            'z': z_score,
            'ker': ker,
            'vol_ratio': vol_ratio
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # --- 1. Data Ingestion ---
        active_symbols = []
        
        # Clean up history for removed symbols
        current_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in current_symbols:
                del self.history[s]

        for symbol, data in prices.items():
            if 'priceUsd' not in data:
                continue
            try:
                price = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            active_symbols.append(symbol)
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # --- 2. Exit Logic ---
        for symbol in list(self.positions.keys()):
            # Handle data loss
            if symbol not in prices:
                pos = self.positions[symbol]
                if self.tick_counter - pos['tick'] > self.max_hold_ticks + 5:
                    del self.positions[symbol]
                continue
                
            current_price = self.history[symbol][-1]
            metrics = self._get_metrics(symbol, current_price)
            if not metrics:
                continue
            
            z = metrics['z']
            tick_age = self.tick_counter - self.positions[symbol]['tick']
            
            # A. Mean Reversion Success
            if z >= self.exit_z_target:
                del self.positions[symbol]
                self.cooldowns[symbol] = 5
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['MEAN_REVERSION_HIT']
                }
                
            # B. Statistical Failure (Stop Loss)
            if z < self.stop_loss_z:
                del self.positions[symbol]
                self.cooldowns[symbol] = 25 # Long penalty for failure
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['STRUCTURAL_BREAK']
                }
                
            # C. Time Limit
            if tick_age >= self.max_hold_ticks:
                del self.positions[symbol]
                self.cooldowns[symbol] = 5
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['TIME_LIMIT']
                }

        # --- 3. Entry Logic ---
        if len(self.positions) >= self.max_positions:
            return None
            
        for symbol in active_symbols:
            if symbol in self.positions or symbol in self.cooldowns:
                continue
                
            # Liquidity Filter
            try:
                liq = float(prices[symbol].get('liquidity', 0))
            except:
                liq = 0
            if liq < self.min_liquidity:
                continue

            current_price = self.history[symbol][-1]
            metrics = self._get_metrics(symbol, current_price)
            if not metrics:
                continue
                
            z = metrics['z']
            ker = metrics['ker']
            vol_ratio = metrics['vol_ratio']
            
            # --- FILTER 1: Volatility Gate ---
            # If short-term volatility is > 1.8x long-term, market is crashing/exploding.
            # Don't step in front of the train.
            if vol_ratio > 1.8:
                continue
                
            # --- FILTER 2: Efficiency Ratio (The Fix) ---
            # KER > 0.4 implies a highly efficient trend (Breakout). 
            # We only fade noise (KER < 0.4).
            if ker > 0.4:
                continue
                
            # --- TRIGGER: Dynamic Z-Score ---
            # If market