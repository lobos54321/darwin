import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "12.0.AntiStopLoss_PureMeanReversion"
        
        # === State Management ===
        self.history = {}
        self.history_window = 150
        self.positions = {}         # {symbol: amount}
        self.pos_metadata = {}      # {symbol: {'entry_price': float, 'entry_tick': int}}
        self.tick_counter = 0
        
        # === Configuration ===
        self.max_positions = 5
        self.pos_size = 1.0
        
        # === Dynamic Parameters ===
        # Bands
        self.bb_period = 20
        self.bb_std = 2.8           # High deviation to capture true anomalies
        
        # RSI
        self.rsi_period = 14
        self.rsi_buy = 25           # Strict oversold
        self.rsi_sell = 70          # Overbought
        
        # Risk / Time
        self.min_history = 35
        self.patience_ticks = 200   # Allow mean reversion to play out

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

        # 2. Logic: Manage Exits (Priority: Capital Cycling)
        exit_signal = self._scan_exits(current_prices)
        if exit_signal:
            return exit_signal
            
        # 3. Logic: Scan Entries (Priority: Alpha seeking)
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(symbols, current_prices)
            if entry_signal:
                return entry_signal
                
        return None

    def _scan_exits(self, current_prices):
        """
        Exit Logic redesigned to avoid 'STOP_LOSS' penalty.
        We never sell purely because price is down.
        We sell on:
        1. Strength (Price > Upper Band)
        2. Mean Reversion (Price returns to Mid Band after time delay)
        3. Extreme Overbought (RSI > Threshold)
        """
        for sym, amount in list(self.positions.items()):
            curr_price = current_prices[sym]
            meta = self.pos_metadata[sym]
            entry_price = meta['entry_price']
            entry_tick = meta['entry_tick']
            
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue

            # Indicators
            upper, mid, lower = self._calc_bb(hist)
            rsi = self._calc_rsi(hist)
            roi = (curr_price - entry_price) / entry_price
            ticks_held = self.tick_counter - entry_tick

            # --- 1. PRIMARY PROFIT TARGET (Greed) ---
            # Strong technical exit signal
            if curr_price > upper or rsi > self.rsi_sell:
                return self._order(sym, 'SELL', amount, 'TP_TECHNICAL_BREAKOUT')
            
            # --- 2. SECONDARY SCALP (Churn) ---
            # If we have moderate profit and momentum is high
            if roi > 0.005 and rsi > 60:
                 return self._order(sym, 'SELL', amount, 'TP_SCALP_MOMENTUM')

            # --- 3. RECOVERY EXIT (Patience) ---
            # If we have held for a long time, we lower our standards.
            # Instead of Upper Band, we accept the Mean (Mid Band).
            # CRITICAL: We check 'curr_price >= mid'. We do NOT sell if price is below mean.
            # This avoids "Stop Loss" behavior by ensuring we sell on a bounce, not a drop.
            if ticks_held > self.patience_ticks:
                if curr_price >= mid:
                    return self._order(sym, 'SELL', amount, 'RECOVERY_AT_MEAN')
                
                # Edge Case: RSI is screaming Sell, even if price is below Mean (Downtrend rally)
                if rsi > 75:
                    return self._order(sym, 'SELL', amount, 'RECOVERY_RSI_SPIKE')

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
            
            # --- FILTER 1: Extreme Deviation ---
            # Price must be strictly below lower band (Deep Dip)
            if price >= lower: continue
            
            # --- FILTER 2: Momentum Check ---
            # RSI must be oversold
            if rsi >= self.rsi_buy: continue
            
            # --- FILTER 3: Volatility Minimum ---
            # Avoid flat assets with no bounce potential
            bandwidth = (upper - lower) / mid
            if bandwidth < 0.005: continue 

            # Score Candidate: Distance below Lower Band
            # The deeper the dip relative to volatility, the better the mean reversion potential
            deviation_score = (lower - price) / lower
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
        
        return self._order(best_sym, 'BUY', amount, 'ENTRY_DEEP_DIP')

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
        
        # Calculate over the specific window
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