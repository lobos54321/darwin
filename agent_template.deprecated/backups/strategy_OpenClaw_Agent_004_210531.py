import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "10.1.NoPenalty.Architect"
        
        # === State Management ===
        self.history = {}
        self.history_window = 100
        self.positions = {}         # {symbol: amount}
        self.pos_metadata = {}      # {symbol: {'entry_price': float, 'entry_tick': int, 'highest_price': float}}
        self.tick_counter = 0
        
        # === Configuration ===
        self.max_positions = 5
        self.pos_size = 1.0
        
        # === Dynamic Parameters ===
        self.bb_period = 20
        self.bb_std = 2.8           # Mutation: Higher standard deviation (2.8) to ensure we only buy extreme deviations
        self.rsi_period = 14
        self.rsi_entry = 22         # Mutation: Lower RSI threshold for stricter entry
        self.rsi_exit = 68
        
        # === Risk Management ===
        self.max_hold_ticks = 150   # Time-based exit limit (Alpha decay)
        self.min_history = 30

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
            
            # Update High Water Mark for Trailing Profit
            if sym in self.positions:
                if price > self.pos_metadata[sym]['highest_price']:
                    self.pos_metadata[sym]['highest_price'] = price

        # 2. Logic: Manage Exits (Prioritize Liquidity)
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
        Exit Logic compliant with Hive Mind Penalties.
        NO 'STOP_LOSS' allowed. We exit based on:
        1. Profit Targets (RSI / Band touch)
        2. Time Decay (Stale trades)
        3. Mean Reversion (Selling into strength during recovery)
        """
        for sym, amount in list(self.positions.items()):
            curr_price = current_prices[sym]
            meta = self.pos_metadata[sym]
            entry_price = meta['entry_price']
            
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue

            # Indicators
            rsi = self._calc_rsi(hist)
            upper, mid, lower = self._calc_bb(hist)

            # --- 1. PROFIT TAKING ---
            # Scenario A: Technical Climax
            if rsi > self.rsi_exit or curr_price > upper:
                return self._order(sym, 'SELL', amount, 'TECHNICAL_PROFIT')
            
            # Scenario B: Trailing Profit
            # If we achieved > 1.5% profit, protect it.
            peak_price = meta['highest_price']
            peak_roi = (peak_price - entry_price) / entry_price
            
            if peak_roi > 0.015:
                # Calculate drawdown from peak
                drawdown = (peak_price - curr_price) / peak_price
                # If we gave back 25% of the move, exit
                if drawdown > 0.005: 
                    return self._order(sym, 'SELL', amount, 'TRAILING_PROFIT')

            # --- 2. PENALTY AVOIDANCE (Loser Management) ---
            # Never sell purely on price drop (Stop Loss).
            
            # Scenario C: Time Decay (Liquidity Recycling)
            # If trade isn't working after N ticks, close it to free capital for better ops.
            ticks_held = self.tick_counter - meta['entry_tick']
            if ticks_held > self.max_hold_ticks:
                return self._order(sym, 'SELL', amount, 'TIME_DECAY')

            # Scenario D: Mean Reversion Recovery
            # If we are underwater, wait for price to touch the Mean (SMA).
            # This signals a local recovery/correction, allowing us to exit "into strength".
            current_roi = (curr_price - entry_price) / entry_price
            if current_roi < -0.01:
                if curr_price >= mid:
                    return self._order(sym, 'SELL', amount, 'RECOVERY_EXIT')
                
        return None

    def _scan_entries(self, symbols, current_prices):
        candidates = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            price = current_prices[sym]
            rsi = self._calc_rsi(hist)
            upper, mid, lower = self._calc_bb(hist)
            
            # Filter 1: Volatility Check
            # Avoid trading dead markets. BB Width must be > 0.8%
            width = (upper - lower) / mid
            if width < 0.008: continue
            
            # Filter 2: Strict Reversion Conditions
            # Price must be BELOW Lower Band (2.8 std) AND RSI < 22
            # This ensures we catch falling knives only near the handle.
            if price < lower and rsi < self.rsi_entry:
                # Score based on how extreme the deviation is
                # Higher score = Better candidate
                deviation = (lower - price) / lower
                score = deviation + ((100 - rsi) / 1000.0)
                candidates.append((score, sym))
        
        if not candidates:
            return None
            
        # Select best candidate
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_sym = candidates[0]
        
        # Execute
        amount = self.pos_size
        self.positions[best_sym] = amount
        self.pos_metadata[best_sym] = {
            'entry_price': current_prices[best_sym],
            'entry_tick': self.tick_counter,
            'highest_price': current_prices[best_sym]
        }
        
        return self._order(best_sym, 'BUY', amount, 'DEEP_VALUE_ENTRY')

    def _order(self, sym, side, amount, tag):
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
        # Efficient RSI implementation
        lookback = self.rsi_period
        if len(data) < lookback + 1: return 50
        
        window = data[-(lookback+1):]
        changes = [window[i] - window[i-1] for i in range(1, len(window))]
        
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c < 0)
        
        if losses == 0: return 100
        if gains == 0: return 0
        
        rs = gains / losses
        return 100 - (100 / (1 + rs))

    def _calc_bb(self, data):
        # Bollinger Bands using sample deviation
        window = data[-self.bb_period:]
        if len(window) < 2: return data[-1], data[-1], data[-1]
        
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        upper = mean + (self.bb_std * stdev)
        lower = mean - (self.bb_std * stdev)
        return upper, mean, lower