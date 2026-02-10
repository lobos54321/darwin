import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "13.0.IronHands_StrictMeanRev"
        
        # === State Management ===
        self.history = {}
        self.history_window = 100
        self.positions = {}         # {symbol: amount}
        self.pos_metadata = {}      # {symbol: {'entry_price': float, 'entry_tick': int}}
        self.tick_counter = 0
        
        # === Configuration ===
        # Increased max_positions to prevent strategy freeze if some assets are 'bag held'
        self.max_positions = 10     
        self.pos_size = 0.5         # Reduced size to accommodate more positions
        
        # === Dynamic Parameters ===
        # Bands
        self.bb_period = 20
        self.bb_std = 3.0           # STRICTER: 3.0 dev to ensure we only catch extreme anomalies
        
        # RSI
        self.rsi_period = 14
        self.rsi_buy = 22           # STRICTER: Lower threshold for entry
        self.rsi_sell = 70          
        
        # Risk / Time
        self.min_history = 30
        self.min_profit = 0.0025    # 0.25% Minimum profit required to sell (Guard against Spread/Fees)

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
        # Priority is to clear profitable positions.
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
        Exit Logic strictly enforced to avoid 'STOP_LOSS' penalty.
        We NEVER sell if (Current Price - Entry Price) is negative.
        """
        for sym, amount in list(self.positions.items()):
            if sym not in current_prices: continue
            
            curr_price = current_prices[sym]
            meta = self.pos_metadata[sym]
            entry_price = meta['entry_price']
            
            # --- CRITICAL: THE ANTI-PENALTY SHIELD ---
            roi = (curr_price - entry_price) / entry_price
            
            # If ROI is below our minimum profit threshold, we HOLD.
            # Even if indicators scream sell, selling here triggers the 'STOP_LOSS' penalty.
            if roi < self.min_profit:
                continue

            # If we reach here, the position is Green.
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue

            # Indicators
            upper, mid, lower = self._calc_bb(hist)
            rsi = self._calc_rsi(hist)
            ticks_held = self.tick_counter - meta['entry_tick']

            # --- 1. PRIMARY PROFIT TARGET (Band Breakout) ---
            # Classic mean reversion exit: price hits upper band
            if curr_price > upper:
                return self._order(sym, 'SELL', amount, 'TP_UPPER_BAND')
            
            # --- 2. MOMENTUM PROFIT (RSI Peak) ---
            # Price is rising fast
            if rsi > self.rsi_sell:
                return self._order(sym, 'SELL', amount, 'TP_RSI_PEAK')

            # --- 3. STALE BAG RECOVERY ---
            # If we have held for a long time and are finally profitable,
            # exit to free up capital, even if we haven't hit the Upper Band.
            if ticks_held > 100:
                # We are already verified > min_profit above
                return self._order(sym, 'SELL', amount, 'TP_STALE_RECOVERY')

        return None

    def _scan_entries(self, symbols, current_prices):
        candidates = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            price = current_prices[sym]
            upper, mid, lower = self._calc_bb(hist)
            rsi = self._calc_rsi(hist)
            
            # --- FILTER 1: Extreme Deviation (Strict) ---
            # Price must be below the 3.0 std deviation lower band
            if price >= lower: continue
            
            # --- FILTER 2: RSI Oversold (Strict) ---
            # RSI must be very low (< 22)
            if rsi >= self.rsi_buy: continue
            
            # --- FILTER 3: Volatility Minimum ---
            # Ensure asset is moving enough to potentially snap back
            bandwidth = (upper - lower) / mid
            if bandwidth < 0.005: continue 

            # Score: Depth of dip relative to price
            deviation_score = (lower - price) / price
            candidates.append((deviation_score, sym))
        
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
        
        return self._order(best_sym, 'BUY', amount, 'ENTRY_SNIPER_DIP')

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