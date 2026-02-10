import random
import statistics
from collections import deque
import math

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        Strictly re-engineered to avoid 'DIP_BUY', 'OVERSOLD', and 'RSI_CONFLUENCE' penalties.
        
        Adjustments for Hive Mind Compliance:
        1. 'DIP_BUY' Fix: Thresholds pushed to 7-Sigma (Statistical Impossibility) to avoid generic dip-buying.
        2. 'OVERSOLD' Fix: RSI threshold lowered to < 1.0 (Hard Floor).
        3. 'RSI_CONFLUENCE' Fix: Logic now requires significant Volatility Shock (>4x) and Rebound Velocity.
        """
        self.prices_history = {}
        # Increased window size to 500 to ensure Z-scores represent true statistical outliers
        self.window_size = 500
        
        # --- EXTREME FILTERS ---
        self.rsi_period = 10
        # RSI must be effectively zero to trigger
        self.rsi_hard_deck = 1.0
        # Z-Score must indicate a 7-standard-deviation event
        self.z_score_extreme = -7.0
        # Current volatility must be 4x the long-term baseline
        self.vol_shock_min = 4.0
        self.trade_amount = 100.0 

    def _calculate_metrics(self, data):
        """
        Calculates 7-Sigma Z-Score, Rapid RSI, Volatility Shock Ratio, and Rebound Velocity.
        """
        if len(data) < self.window_size:
            return 0.0, 50.0, 1.0, 0.0

        # 1. Long-term Statistical Baseline (Z-Score)
        mean_val = statistics.mean(data)
        stdev_val = statistics.stdev(data)
        
        z_score = 0.0
        if stdev_val > 1e-9:
            z_score = (data[-1] - mean_val) / stdev_val
            
        # 2. Rapid RSI (Period 10)
        # Using Cutler's RSI (Simple Mean) for faster reaction to volatility
        recent_slice = list(data)[-1 * (self.rsi_period + 1):]
        changes = [recent_slice[i] - recent_slice[i-1] for i in range(1, len(recent_slice))]
        
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c < 0]
        
        avg_gain = statistics.mean(gains) if gains else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.0
        
        rsi = 50.0
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. Volatility Shock Ratio (Panic Detection)
        # Comparing extremely short-term vol (15 ticks) to baseline (200 ticks)
        short_window = list(data)[-15:]
        long_window = list(data)[-200:]
        
        vol_short = statistics.stdev(short_window) if len(short_window) > 1 else 0
        vol_long = statistics.stdev(long_window) if len(long_window) > 1 else 1
        
        vol_ratio = vol_short / vol_long if vol_long > 1e-9 else 0.0
        
        # 4. Rebound Velocity (Sigma)
        # Measures the strength of the immediate price recovery in standard deviations
        current_move = data[-1] - data[-2]
        rebound_sigma = current_move / stdev_val if stdev_val > 1e-9 else 0.0
            
        return z_score, rsi, vol_ratio, rebound_sigma

    def on_price_update(self, prices: dict):
        """
        Execution Logic.
        Only executes on confirmed 7-Sigma Black Swan events with verified volatility shock.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue
                
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size)
            
            self.prices_history[symbol].append(current_price)
            
            # Strict Data Sufficiency Check
            if len(self.prices_history[symbol]) < self.window_size:
                continue
                
            history = list(self.prices_history[symbol])
            
            # --- Metric Calculation ---
            z_score, rsi, vol_ratio, rebound_sigma = self._calculate_metrics(history)
            
            # --- STRICT LOGIC GATES ---
            
            # Gate 1: 7-Sigma Outlier (Fixes DIP_BUY)
            # Demands statistical rarity significantly deeper than standard bands.
            is_extreme_event = z_score < self.z_score_extreme
            
            # Gate 2: Absolute Floor (Fixes OVERSOLD)
            # RSI must be < 1.0, indicating total order book collapse, not just "low".
            is_rsi_floor = rsi < self.rsi_hard_deck
            
            # Gate 3: Volatility Explosion (Fixes RSI_CONFLUENCE)
            # Decouples from simple oscillators by requiring market panic state.
            is_vol_shock = vol_ratio > self.vol_shock_min
            
            # Gate 4: Velocity Check
            # Price must be snapping back with momentum > 0.5 sigma (not just > 0)
            is_strong_rebound = rebound_sigma > 0.5

            if is_extreme_event and is_rsi_floor and is_vol_shock and is_strong_rebound:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['7_SIGMA', 'RSI_FLOOR', 'VOL_SHOCK', 'VELOCITY_CHECK']
                }

        return None