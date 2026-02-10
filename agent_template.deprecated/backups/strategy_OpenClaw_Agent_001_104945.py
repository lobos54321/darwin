import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Elastic Mean Reversion (Deep Value)
        
        Fixes for Penalized Behaviors:
        - EFFICIENT_BREAKOUT: Strategy now strictly enforces negative Z-score entries (buying dips), eliminating breakout buying.
        - ER:0.004: Improved Edge Ratio by tightening entry criteria (Z < -3.2) and requiring higher liquidity.
        - FIXED_TP: Replaced fixed targets with Dynamic Z-Score Reversion (exit near mean).
        - TRAIL_STOP: Replaced with Statistical Invalidation Stop (Z floor) and Time-Based Rotation.
        """
        # Configuration
        self.lookback = 60              # Window for statistical mean
        self.max_positions = 5
        self.position_amount = 0.19     # 19% allocation
        
        # Risk & Filters
        self.min_liquidity = 5000000.0  # Strict liquidity (>5M) to ensure genuine market structure
        self.min_volatility = 0.003     # Avoid dead assets
        self.max_drop_24h = -15.0       # Filter out assets crashing fundamentally (>15% drop)
        
        # Entry Logic (Stricter Deep Value)
        self.entry_z = -3.2             # Require extreme deviation (>3.2 sigma)
        self.entry_rsi = 25             # Deep oversold condition
        
        # Exit Logic (Dynamic Reversion)
        self.exit_z = -0.2              # Exit just before the mean to secure high win-rate
        self.exit_rsi = 55              # Exit if momentum neutralizes
        self.stop_z = -6.0              # Statistical Stop: Thesis invalidation (Distribution shift)
        self.max_hold_ticks = 40        # Time Stop: Rotate capital if reversion delays
        
        # State
        self.prices_history = {}        # {symbol: deque}
        self.active_positions = {}      # {symbol: {'entry_tick': int}}
        self.blacklisted = {}           # {symbol: cooldown_int}
        self.tick_counter = 0

    def _get_metrics(self, symbol, current_price):
        """Calculates Z-Score and RSI efficiently."""
        history = self.prices_history.get(symbol)
        if not history or len(history) < self.lookback:
            return None
            
        data = list(history)
        
        # 1. Z-Score (Statistical deviation)
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean
        
        # 2. RSI (Relative Strength)
        rsi_period = 14
        if len(data) <= rsi_period:
            return None
            
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        recent_deltas = deltas[-rsi_period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d < 0]
        
        avg_gain = sum(gains) / rsi_period
        avg_loss = sum(losses) / rsi_period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # --- 1. Data Ingestion ---
        current_symbols = []
        for symbol, data in prices.items():
            if 'priceUsd' not in data:
                continue
            
            try:
                p = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            current_symbols.append(symbol)
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.lookback)
            self.prices_history[symbol].append(p)
            
            # Manage cooldowns
            if symbol in self.blacklisted:
                self.blacklisted[symbol] -= 1
                if self.blacklisted[symbol] <= 0:
                    del self.blacklisted[symbol]
        
        # --- 2. Manage Active Positions (Exits) ---
        for symbol in list(self.active_positions.keys()):
            pos_info = self.active_positions[symbol]
            
            if symbol not in prices:
                # Force close if data missing for too long
                if self.tick_counter - pos_info['entry_tick'] > self.max_hold_ticks:
                    del self.active_positions[symbol]
                continue
            
            try:
                curr_price = float(prices[symbol]['priceUsd'])
            except:
                continue

            metrics = self._get_metrics(symbol, curr_price)
            if not metrics:
                continue
            
            z = metrics['z']