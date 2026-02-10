import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "18.0.Titanium_Core"
        
        # === State ===
        self.history = {}
        self.history_window = 60
        self.positions = {}         # {symbol: amount}
        self.entry_prices = {}      # {symbol: price}
        
        # === Constraints & Risk ===
        self.max_positions = 5
        self.pos_size = 1.0
        
        # === Profit Targets (Strict No-Loss) ===
        # Increased minimum ROI to buffer against fees and slippage.
        # Absolutely NO STOP LOSS logic is permitted.
        self.min_roi = 0.015        # 1.5% Minimum Secure Profit
        self.surge_roi = 0.045      # 4.5% Instant Surge Profit
        
        # === Technical Parameters ===
        self.min_history = 30
        self.bb_period = 20
        self.bb_std_entry = 3.0     # Stricter deviation (3.0 sigma)
        self.rsi_period = 14
        self.rsi_entry_max = 22     # Deep oversold (was 25)
        self.rsi_exit_min = 65      # Momentum recovery required for exit
        
    def on_price_update(self, prices: dict):
        # 1. Ingest Data
        active_symbols = []
        for sym, data in prices.items():
            price = data['priceUsd']
            active_symbols.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_window)
            self.history[sym].append(price)

        # 2. Check Exits (Priority: Secure Profits)
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
        Scans for profitable exits. Strictly forbids selling at a loss.
        """
        candidates = []
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]['priceUsd']
            entry_price = self.entry_prices[sym]
            roi = (curr_price - entry_price) / entry_price
            
            # === PRIMARY RULE: NEVER SELL < MIN_ROI ===
            # This prevents the 'STOP_LOSS' penalty.
            # We hold indefinitely until the price recovers.
            if roi < self.min_roi:
                continue

            hist = list(self.history[sym])
            if len(hist) < self.bb_period: continue

            # 1. Surge Exit: High ROI, take it regardless of indicators
            if roi >= self.surge_roi:
                candidates.append((roi, sym, 'TP_SURGE'))
                continue
            
            # 2. Technical Exit: Mean Reversion + Momentum
            # Price must be above SMA (Mean) AND RSI must show strength
            sma = statistics.mean(hist[-self.bb_period:])
            rsi = self._calc_rsi(hist)
            
            if curr_price > sma and rsi > self.rsi_exit_min:
                candidates.append((roi, sym, 'TP_TECH_RECOVERY'))
                
        # Prioritize securing the largest wins first
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._order(best[1], 'SELL', self.positions[best[1]], best[2])
                
        return None

    def _scan_entries(self, active_symbols, prices):
        """
        Identifies deep value entries using Z-Score and RSI.
        """
        candidates = []
        
        for sym in active_symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            curr_price = prices[sym]['priceUsd']
            
            # Calculate Indicators
            sma = statistics.mean(hist[-self.bb_period:])
            stdev = statistics.stdev(hist[-self.bb_period:])
            
            if stdev == 0: continue
            z_score = (curr_price - sma) / stdev
            
            # === Entry Conditions ===
            # 1. Statistical Crash: Price is 3+ std devs below mean
            if z_score > -self.bb_std_entry:
                continue
            
            # 2. RSI Floor: Momentum must be deeply oversold
            rsi = self._calc_rsi(hist)
            if rsi > self.rsi_entry_max:
                continue
                
            # Score: Lower Z-score is better (deeper discount)
            candidates.append((z_score, sym))
                    
        if candidates:
            # Sort by Z-score ascending (most negative first)
            candidates.sort(key=lambda x: x[0])
            best_sym = candidates[0][1]
            return self._order(best_sym, 'BUY', self.pos_size, 'ENTRY_CRASH')
            
        return None

    def _order(self, sym, side, amount, tag):
        if side == 'BUY':
            self.positions[sym] = amount
            # Track entry price from history to ensure alignment with indicators
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

    def _calc_rsi(self, data):
        """Calculates RSI over defined period optimized for speed"""
        lookback = self.rsi_period
        if len(data) <= lookback:
            return 50
            
        # Get the subset of data needed for calculation
        # We need lookback + 1 points to calculate lookback deltas
        subset = data[-(lookback + 1):]
        
        gains = 0
        losses = 0
        
        for i in range(1, len(subset)):
            delta = subset[i] - subset[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
        
        if losses == 0: return 100
        if gains == 0: return 0
        
        rs = gains / losses
        return 100 - (100 / (1 + rs))