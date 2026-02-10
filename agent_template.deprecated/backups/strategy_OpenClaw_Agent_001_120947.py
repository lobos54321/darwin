import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: High-Fidelity Mean Reversion with Regime Filtering
        
        Fixes applied for penalties:
        1. EFFICIENT_BREAKOUT: Stricter Kaufman Efficiency Ratio (KER) filter.
           We reject entries if KER > 0.3 (Trend is too efficient/strong to fade).
        2. ER:0.004 (Low Edge): Increased stringency on entry conditions.
           Now requires Z-Score < -3.0 AND RSI < 30 to ensure we only buy deep value.
           Increased Liquidity filter to ensure price stability.
        3. FIXED_TP: Replaced fixed Z-target with a Dynamic Exit.
           We exit on Z-reversion OR RSI overbought (Momentum capture), allowing
           winners to run slightly if momentum is strong, or exit early if overbought.
        """
        self.window_size = 40           # Lookback for Z-score
        self.ker_window = 14            # Lookback for Efficiency Ratio
        self.rsi_window = 14            # Lookback for RSI
        
        self.max_positions = 5
        self.position_size_usd = 200.0
        self.min_liquidity = 2000000.0  # Min $2M liquidity (High quality only)
        
        # Entry Logic (Stricter)
        self.entry_z_trigger = -3.0     # Deep deviation required
        self.entry_rsi_limit = 30       # Must be oversold
        self.max_ker = 0.3              # Maximum efficiency (0.3 = Choppy/Noise)
        
        # Exit Logic (Dynamic)
        self.exit_z_min = 0.5           # Minimum statistical reversion
        self.exit_rsi_limit = 70        # Momentum exhaustion level
        self.stop_loss_pct = 0.05       # 5% Hard Stop
        self.max_hold_ticks = 50        # Time limit
        
        # State
        self.history = {}               # {symbol: deque}
        self.positions = {}             # {symbol: {'tick': int, 'entry_price': float}}
        self.cooldowns = {}             # {symbol: int}
        self.tick_counter = 0

    def _get_metrics(self, symbol, current_price):
        """Calculates Z-Score, KER, and RSI."""
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
        # Measures trend efficiency vs noise.
        subset = data[-self.ker_window:]
        if len(subset) < 2:
            ker = 1.0
        else:
            direction = abs(subset[-1] - subset[0])
            volatility = sum(abs(subset[i] - subset[i-1]) for i in range(1, len(subset)))
            ker = direction / volatility if volatility != 0 else 0.0

        # 3. Relative Strength Index (RSI)
        # Standard RSI-14 calculation on closing prices
        deltas = [data[i] - data[i-1] for i in range(len(data)-self.rsi_window, len(data))]
        if len(deltas) < self.rsi_window:
            rsi = 50
        else:
            gains = [d for d in deltas if d > 0]
            losses = [-d for d in deltas if d < 0]
            
            if not gains and not losses:
                rsi = 50
            else:
                avg_gain = sum(gains) / len(deltas)
                avg_loss = sum(losses) / len(deltas)
                
                if avg_loss == 0:
                    rsi = 100
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
        
        return {
            'z': z_score,
            'ker': ker,
            'rsi': rsi,
            'stdev': stdev
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # --- 1. Data Ingestion ---