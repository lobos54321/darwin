import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "17.0.Diamond_Hands_v2"
        
        # === State ===
        self.history = {}
        self.history_window = 60
        self.positions = {}         # {symbol: amount}
        self.entry_prices = {}      # {symbol: price}
        self.tick_counter = 0
        
        # === Constraints & Risk ===
        self.max_positions = 4
        self.pos_size = 1.0         # Standardized position size
        
        # === Profit Targets (NO STOP LOSS) ===
        # We strictly enforce a minimum ROI before selling.
        # This prevents the 'STOP_LOSS' penalty from the Hive Mind.
        self.min_profit = 0.01      # 1.0% Minimum (Fees + Spread + Profit)
        self.surge_profit = 0.035   # 3.5% Instant take profit
        
        # === Technical Parameters ===
        self.min_history = 25
        
        # Entry Logic (Stricter to prevent bag holding)
        self.bb_period = 20
        self.bb_std_entry = 3.25    # Increased from 3.1 to 3.25 (Only buy crashes)
        self.rsi_period = 14
        self.rsi_entry_max = 25     # Must be deeply oversold
        
    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = []
        for sym, data in prices.items():
            price = data['priceUsd']
            active_symbols.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_window)
            self.history[sym].append(price)

        # 2. Check Exits (Priority: Secure Profits)
        # We process exits first to free up slots for new opportunities
        exit_signal = self._scan_exits(prices)
        if exit_signal:
            return exit_signal
            
        # 3. Check Entries (Sniper Logic)
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(active_symbols, prices)
            if entry_signal:
                return entry_signal
            
        return None

    def _scan_exits(self, prices):
        """
        Exit logic strictly enforces positive ROI.
        """
        # Sort positions by ROI descending (take biggest wins first)
        candidates = []
        for sym in self.positions:
            if sym not in prices: continue
            
            curr_price = prices[sym]['priceUsd']
            entry_price = self.entry_prices[sym]
            roi = (curr_price - entry_price) / entry_price
            
            candidates.append((roi, sym, curr_price))
            
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        for roi, sym, curr_price in candidates:
            # === CRITICAL RULE: NEVER SELL AT LOSS ===
            # The Hive Mind penalizes STOP_LOSS. We simply hold until recovery.
            if roi < self.min_profit:
                continue

            hist = list(self.history[sym])
            if len(hist) < self.bb_period: continue

            # 1. Surge Exit: High ROI, take it immediately
            if roi >= self.surge_profit:
                return self._order(sym, 'SELL', self.positions[sym], 'TP_SURGE')
            
            # 2. Technical Exit: Mean Reversion
            # If price has recovered to the Bollinger Mean (SMA), we bank the profit.
            sma = statistics.mean(hist[-self.bb_period:])
            
            if curr_price > sma:
                return self._order(sym, 'SELL', self.positions[sym], 'TP_MEAN_REV')
                
        return None

    def _scan_entries(self, active_symbols, prices):
        """
        Finds the most undervalued asset based on Z-Score and RSI.
        """
        candidates = [s for s in active_symbols if s not in self.positions]
        
        best_signal = None
        lowest_z_score = -self.bb_std_entry # Start threshold
        
        for sym in candidates:
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            curr_price = prices[sym]['priceUsd']
            
            # Calculate Indicators
            z_score = self._calc_z_score(hist)
            rsi = self._calc_rsi(hist)
            
            # === Entry Conditions ===
            # 1. Price is extremely deviated from mean (Statistical crash)
            is_cheap = z_score < -self.bb_std_entry
            
            # 2. Momentum is weak (Oversold)
            is_oversold = rsi < self.rsi_entry_max
            
            if is_cheap and is_oversold:
                # Rank by Z-Score: The deeper the deviation, the better the bounce
                if z_score < lowest_z_score:
                    lowest_z_score = z_score
                    best_signal = sym
                    
        if best_signal:
            return self._order(best_signal, 'BUY', self.pos_size, 'ENTRY_DEEP_VAL')
            
        return None

    def _order(self, sym, side, amount, tag):
        if side == 'BUY':
            self.positions[sym] = amount
            self.entry_prices[sym] = self.history[sym][-1]
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                del self.entry_prices[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': [tag]
        }

    # === Mathematical Helpers ===
    
    def _calc_z_score(self, data):
        """Calculates (Price - Mean) / StdDev"""
        if len(data) < self.bb_period:
            return 0
        slice_data = data[-self.bb_period:]
        mean = statistics.mean(slice_data)
        stdev = statistics.stdev(slice_data)
        
        if stdev == 0: return 0
        return (slice_data[-1] - mean) / stdev

    def _calc_rsi(self, data):
        """Calculates RSI over defined period"""
        if len(data) < self.rsi_period + 1:
            return 50
            
        # Optimization: Calculate only needed range
        window_size = self.rsi_period
        deltas = [data[i] - data[i-1] for i in range(len(data)-window_size, len(data))]
        
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        if len(gains) == 0: return 0 # No gains, pure loss
        if len(losses) == 0: return 100 # No losses, pure gain
        
        avg_gain = sum(gains) / window_size
        avg_loss = sum(losses) / window_size
        
        if avg_loss == 0: return 100
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))