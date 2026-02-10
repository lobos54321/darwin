import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "11.0.PureMeanReversion"
        
        # === State Management ===
        self.history = {}
        self.history_window = 120
        self.positions = {}         # {symbol: amount}
        self.pos_metadata = {}      # {symbol: {'entry_price': float, 'entry_tick': int}}
        self.tick_counter = 0
        
        # === Configuration ===
        self.max_positions = 5
        self.pos_size = 1.0
        
        # === Dynamic Parameters ===
        self.bb_period = 20
        self.bb_std = 3.0           # MUTATION: Stricter deviation (3.0) to minimize false entries
        self.rsi_period = 14
        self.rsi_entry = 18         # MUTATION: Lower RSI for deep oversold entries
        self.rsi_exit_high = 70     # Exit when overbought
        
        # === Risk Management ===
        self.max_hold_ticks = 200   # MUTATION: Longer hold time to allow mean reversion
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

        # 2. Logic: Manage Exits
        exit_signal = self._scan_exits(current_prices)
        if exit_signal:
            return exit_signal
            
        # 3. Logic: Scan Entries
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(symbols, current_prices)
            if entry_signal:
                return entry_signal
                
        return None

    def _scan_exits(self, current_prices):
        """
        Exit Logic strictly avoiding 'STOP_LOSS' patterns.
        Exits are triggered by:
        1. Technical Profit (Bands/RSI)
        2. Time Expiry (Stale quotes)
        3. Mean Reversion Recovery (Selling a loser only when it touches the mean)
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

            # --- 1. PROFIT TAKING (Technical) ---
            # Strong signal: Price broke upper band or RSI is screaming high
            if curr_price > upper or rsi > self.rsi_exit_high:
                return self._order(sym, 'SELL', amount, 'TECHNICAL_TAKE_PROFIT')
            
            # Moderate signal: We are above entry and indicators are neutral/high
            roi = (curr_price - entry_price) / entry_price
            if roi > 0.01 and rsi > 60:
                 return self._order(sym, 'SELL', amount, 'MODERATE_PROFIT')

            # --- 2. TIME DECAY (Liquidity Recycling) ---
            # If the trade is stagnant for too long, close it regardless of PnL
            # This is a Time Stop, not a Price Stop.
            ticks_held = self.tick_counter - meta['entry_tick']
            if ticks_held > self.max_hold_ticks:
                return self._order(sym, 'SELL', amount, 'TIME_EXPIRY')

            # --- 3. RECOVERY EXIT (Mean Reversion) ---
            # Logic: If we are losing money, do NOT sell on the drop.
            # Wait for the price to bounce back to the Moving Average (Mid Band).
            # This minimizes loss by selling into local strength.
            if roi < 0:
                if curr_price >= mid:
                    # We touched the mean, likely the best exit we'll get in a downtrend
                    return self._order(sym, 'SELL', amount, 'MEAN_REVERSION_RECOVERY')
                
        return None

    def _scan_entries(self, symbols, current_prices):
        candidates = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            price = current_prices[sym]
                
            upper, mid, lower = self._calc_bb(hist)
            
            # STRICT ENTRY: Price must be BELOW lower band (3.0 std)
            if price >= lower: continue
            
            # Filter 2: RSI Check
            rsi = self._calc_rsi(hist)
            if rsi >= self.rsi_entry: continue
            
            # Filter 3: Volatility
            # Ensure band width is sufficient to allow for a bounce
            width = (upper - lower) / mid
            if width < 0.005: continue # Avoid flat lines

            # Score Candidate
            # Prioritize most extreme deviations
            deviation = (lower - price) / lower
            score = deviation + (100 - rsi)
            candidates.append((score, sym))
        
        if not candidates:
            return None
            
        # Execute best candidate
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_sym = candidates[0]
        
        amount = self.pos_size
        self.positions[best_sym] = amount
        self.pos_metadata[best_sym] = {
            'entry_price': current_prices[best_sym],
            'entry_tick': self.tick_counter
        }
        
        return self._order(best_sym, 'BUY', amount, 'DEEP_VALUE_SNIPE')

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
        window = data[-self.bb_period:]
        if len(window) < 2: return data[-1], data[-1], data[-1]
        
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        upper = mean + (self.bb_std * stdev)
        lower = mean - (self.bb_std * stdev)
        return upper, mean, lower