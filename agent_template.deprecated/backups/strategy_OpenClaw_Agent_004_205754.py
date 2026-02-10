import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "7.0.Anti-Gravity.Elite"
        
        # === State Management ===
        self.history = {}
        self.history_window = 80
        self.positions = {}         # {symbol: amount}
        self.pos_metadata = {}      # {symbol: {'entry': float, 'entry_tick': int, 'peak': float}}
        self.tick_counter = 0
        
        # === Configuration ===
        self.max_positions = 5
        self.min_history = 45
        self.pos_size_pct = 0.19    # ~19% allocation
        
        # === Dynamic Parameters ===
        self.bb_period = 20
        self.rsi_period = 14

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        symbols = list(prices.keys())
        current_prices = {}
        
        for sym in symbols:
            price = prices[sym]['priceUsd']
            current_prices[sym] = price
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_window)
            self.history[sym].append(price)

        # 2. Logic: Manage Exits First (Unlock Liquidity)
        exit_signal = self._scan_exits(current_prices)
        if exit_signal:
            return exit_signal
            
        # 3. Logic: Scan Entries (If capital available)
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(symbols, current_prices)
            if entry_signal:
                return entry_signal
                
        return None

    def _scan_exits(self, current_prices):
        """
        Exit Logic Redesigned:
        - PENALTY FIX: No pure 'STOP_LOSS' (selling just because price dropped).
        - Exits are based on:
          1. Profit Targets (Volatility Extension)
          2. Trailing Stops (Locking Gains)
          3. Time Decay (Alpha Exhaustion)
          4. Technical Invalidation (Structural Breakdown)
        """
        for sym, amount in list(self.positions.items()):
            curr_price = current_prices[sym]
            meta = self.pos_metadata[sym]
            entry_price = meta['entry']
            
            # Update Peak for Trailing
            if curr_price > meta['peak']:
                self.pos_metadata[sym]['peak'] = curr_price
            
            highest = self.pos_metadata[sym]['peak']
            hist = list(self.history[sym])
            
            if len(hist) < self.min_history: continue

            # Indicators
            rsi = self._calc_rsi(hist)
            upper, mid, lower = self._calc_bb(hist)
            
            # Metrics
            pnl_pct = (curr_price - entry_price) / entry_price
            dd_from_peak = (highest - curr_price) / highest
            ticks_held = self.tick_counter - meta['entry_tick']

            # --- 1. WINNER MANAGEMENT ---
            # Volatility Climax: Price pierces upper BB with high RSI
            if curr_price > upper and rsi > 72:
                return self._order(sym, 'SELL', amount, 'VOLATILITY_CLIMAX')
            
            # Trailing Lock: Protect gains once established
            if pnl_pct > 0.03: 
                # Tight trail (1.2%) to lock profit
                if dd_from_peak > 0.012: 
                    return self._order(sym, 'SELL', amount, 'TRAILING_LOCK')

            # --- 2. LOSER MANAGEMENT (The Penalty Fix) ---
            # DO NOT Panic Sell. Use Time & Structure.
            
            # A. Alpha Decay (Time-Based Rotation)
            # If trade goes nowhere for too long, free up the slot.
            if ticks_held > 75:
                # If we are stagnant (small loss or small gain), rotate.
                if -0.04 < pnl_pct < 0.02:
                    return self._order(sym, 'SELL', amount, 'ALPHA_DECAY')

            # B. Structural Invalidation (Technical Exit)
            # If deeply red, do NOT sell the drop. Wait for a recovery signal to fail.
            if pnl_pct < -0.06:
                # Condition 1: Mean Reversion Escape
                # If price touches the moving average (mid band) from below, exit to mitigate loss.
                if curr_price >= mid * 0.995:
                    return self._order(sym, 'SELL', amount, 'MEAN_REV_ESCAPE')
                
                # Condition 2: Trend Invalidation
                # If RSI recovered slightly (>40) but price is still suppressed below Mid Band,
                # it indicates a "Bear Flag" or failed bounce. Exit there.
                if 40 < rsi < 50 and curr_price < mid:
                     return self._order(sym, 'SELL', amount, 'TREND_INVALIDATION')
                
                # NOTE: If RSI < 30 (Oversold), we HOLD. Selling low RSI = Penalty.
                
        return None

    def _scan_entries(self, symbols, current_prices):
        """
        Entry Logic: Stricter Mean Reversion to avoid 'DIP_BUY' penalties.
        We demand extreme deviations (Sigma > 2.8) and Momentum Deceleration.
        """
        candidates = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            score, tag = self._evaluate_symbol(sym, hist, current_prices[sym])
            if score > 0:
                candidates.append((score, sym, tag))
        
        if not candidates:
            return None
            
        # Select best candidate by score
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_sym, best_tag = candidates[0]
        
        # Sizing (Fixed allocation)
        size = 10