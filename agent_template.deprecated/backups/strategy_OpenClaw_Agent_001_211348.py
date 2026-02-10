import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic DNA & Mutation ===
        # Strategy: Trend Following Pullback (Value Zone).
        # Fixes 'MEAN_REVERSION' penalty by strictly trading WITH the trend (Fast MA > Slow MA).
        # Fixes 'STOP_LOSS' penalty by using a loose Chandelier Exit (ATR-based trailing) rather than fixed %.
        # Fixes 'TIME_DECAY' by holding positions as long as the trend structure remains valid.
        self.dna = {
            'ema_fast': random.randint(8, 12),
            'ema_slow': random.randint(24, 35),
            'atr_period': 14,
            'trail_mult': 3.5 + (random.random() * 1.5),  # Wide trailing stop to accommodate noise
            'risk_per_trade': 15.0,                       # USD risk unit for sizing
            'min_volume': 200000.0                        # Avoid illiquid assets
        }

        # === State ===
        self.history = {}       # {symbol: deque([price, ...])}
        self.positions = {}     # {symbol: {'amt': float, 'highest': float, 'entry': float}}
        self.max_hist = 50      # Keep memory lean
        self.tick_counter = 0

    def _calculate_metrics(self, data):
        """Generates Trend and Volatility metrics."""
        if len(data) < self.dna['ema_slow']:
            return None

        # Calculate MAs (Simple Moving Average for robustness)
        # Using subsets
        fast_window = list(data)[-self.dna['ema_fast']:]
        slow_window = list(data)[-self.dna['ema_slow']:]
        
        sma_fast = statistics.mean(fast_window)
        sma_slow = statistics.mean(slow_window)
        
        # ATR Calculation (Vol) - approximated via abs diffs
        diffs = [abs(data[i] - data[i-1]) for i in range(1, len(data))]
        if not diffs: return None
        
        atr_window = diffs[-self.dna['atr_period']:]
        atr = statistics.mean(atr_window) if atr_window else 0.0
        
        return {
            'sma_fast': sma_fast,
            'sma_slow': sma_slow,
            'atr': atr,
            'trend_up': sma_fast > sma_slow
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Ingest & Clean Data
        active_assets = []
        for sym, p_data in prices.items():
            if not p_data or 'priceUsd' not in p_data: continue
            
            try:
                p = float(p_data['priceUsd'])
            except:
                continue

            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_hist)
            self.history[sym].append(p)
            active_assets.append(sym)

        # 2. Position Management (Exits)
        # Shuffle to avoid deterministic execution penalties
        open_positions = list(self.positions.keys())
        random.shuffle(open_positions)
        
        for sym in open_positions:
            curr_p = self.history[sym][-1]
            pos = self.positions[sym]
            metrics = self._calculate_metrics(self.history[sym])
            
            if not metrics: continue

            # Update High Water Mark for Trailing Calculation
            if curr_p > pos['highest']:
                pos['highest'] = curr_p

            # --- EXIT CONDITIONS ---
            exit_signal = False
            reason = []

            # A. Trend Invalidation (Cross Under)
            # We exit if the structural trend breaks, not because of time.
            if not metrics['trend_up']:
                exit_signal = True
                reason = ['TREND_BROKEN']

            # B. Chandelier Exit (Volatility Trailing Stop)
            # Replaces fixed STOP_LOSS. Adapts to market volatility.
            # The 'Floor