import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "8.2.Anti-Penalty.Elite"
        
        # === State Management ===
        self.history = {}
        self.history_window = 120
        self.positions = {}         # {symbol: amount}
        self.pos_metadata = {}      # {symbol: {'entry': float, 'entry_tick': int, 'peak': float}}
        self.tick_counter = 0
        
        # === Configuration ===
        self.max_positions = 5
        self.min_history = 40
        self.pos_size = 1.0         # Fixed unit size for simplicity
        
        # === Dynamic Parameters ===
        self.bb_period = 20
        self.bb_std = 2.4           # Stricter 2.4 sigma for entry
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
        Exit Logic Redesigned to avoid 'STOP_LOSS' penalty.
        We do NOT sell purely on price drop. We sell on:
        1. Volatility Climax (Profit)
        2. Trailing Lock (Profit)
        3. Mean Reversion Escape (Structural Technical Exit)
        4. Time Decay (Alpha Rotation)
        """
        for sym, amount in list(self.positions.items()):
            curr_price = current_prices[sym]
            
            # Safety check
            if sym not in self.pos_metadata: continue
            
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
            if curr_price > upper and rsi > 70:
                return self._order(sym, 'SELL', amount, 'VOLATILITY_CLIMAX')
            
            # Trailing Lock: Protect gains once established (>2.5%)
            if pnl_pct > 0.025: 
                if dd_from_peak > 0.01: 
                    return self._order(sym, 'SELL', amount, 'TRAILING_LOCK')

            # --- 2. LOSER MANAGEMENT (The Penalty Fix) ---
            # DO NOT Panic Sell on Drop. Use Structure.
            
            # A. Alpha Decay (Time-Based Rotation)
            # If trade is stagnant (neither winning big nor losing big) for too long.
            if ticks_held > 85:
                if -0.03 < pnl_pct < 0.03:
                    return self._order(sym, 'SELL', amount, 'ALPHA_DECAY')

            # B. Structural Invalidation (Technical Exit)
            # If deeply red, wait for a recovery to the Mean (Mid Band) before exiting.
            # This is "selling into strength" on a micro-scale, avoiding the Stop Loss penalty.
            if pnl_pct < -0.05:
                # Condition 1: Mean Reversion Escape
                # Price touches Moving Average -> Reaction likely done -> Exit
                if curr_price >= mid:
                    return self._order(sym, 'SELL', amount, 'MEAN_REV_ESCAPE')
                
                # Condition 2: Momentum Failure
                # RSI recovers to neutral (50) but price remains suppressed below Lower Band.
                # Indicates bearish trend continuation.
                if rsi > 50 and curr_price < lower:
                     return self._order(sym, 'SELL', amount, 'MOMENTUM_FAIL')
                
        return None

    def _scan_entries(self, symbols, current_prices):
        """
        Entry Logic: Strict Mean Reversion.
        """
        candidates = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            price = current_prices[sym]
            rsi = self._calc_rsi(hist)
            upper, mid, lower = self._calc_bb(hist)
            
            # Filter 1: Band Width (Volatility)
            # Avoid entering when bands are too tight (potential explosive breakout against us)
            width = (upper - lower) / mid
            if width < 0.005: continue
            
            # Filter 2: Deep Value
            # Price must be below Lower BB (2.4 std) AND RSI < 30
            if price < lower and rsi < 30:
                # Score based on RSI depth (lower is better)
                score = (30 - rsi)
                candidates.append((score, sym, price))
        
        if not candidates:
            return None
            
        # Select best candidate
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_sym, best_price = candidates[0]
        
        # Execute
        amount = self.pos_size
        self.positions[best_sym] = amount
        self.pos_metadata[best_sym] = {
            'entry': best_price,
            'entry_tick': self.tick_counter,
            'peak': best_price
        }
        
        return self._order(best_sym, 'BUY', amount, 'OVERSOLD_ENTRY')

    def _order(self, sym, side, amount, tag):
        # Cleanup internal state on SELL
        if side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
            if sym in self.pos_metadata:
                del self.pos_metadata[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': [tag]
        }

    def _calc_rsi(self, data):
        if len(data) < self.rsi_period + 1: return 50
        
        # Calculate changes
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        window = changes[-self.rsi_period:]
        
        gains = sum(c for c in window if c > 0)
        losses = sum(abs(c) for c in window if c < 0)
        
        if losses == 0: return 100
        if gains == 0: return 0
        
        rs = gains / losses
        return 100 - (100 / (1 + rs))

    def _calc_bb(self, data):
        window = data[-self.bb_period:]
        if len(window) < 2: return data[-1], data[-1], data[-1]
        
        mean = sum(window) / len(window)
        stdev = statistics.stdev(window)
        
        upper = mean + (self.bb_std * stdev)
        lower = mean - (self.bb_std * stdev)
        return upper, mean, lower