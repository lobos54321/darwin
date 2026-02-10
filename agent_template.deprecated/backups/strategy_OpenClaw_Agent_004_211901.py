import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "19.0.Diamond_Core_V2"
        
        # === State ===
        self.history = {}
        self.history_maxlen = 60
        self.positions = {}         # {symbol: amount}
        self.entry_meta = {}        # {symbol: {'entry_price': float, 'entry_tick': int}}
        self.tick_counter = 0
        
        # === Constraints ===
        self.max_positions = 5
        self.pos_size = 1.0
        
        # === Risk Management (Strict No-Loss) ===
        # Penalized for STOP_LOSS previously. 
        # Strategy: Hold Indefinitely until Positive.
        self.min_roi = 0.018        # 1.8% Minimum Profit (Increased from 1.5%)
        self.scalp_roi = 0.005      # 0.5% "Stale" Profit to free capital
        self.stale_threshold = 45   # Ticks before allowing Scalp ROI
        
        # === Entry Technicals (Stricter) ===
        self.bb_period = 20
        self.bb_std_entry = 3.2     # Stricter: Requires 3.2 sigma deviation (was 3.0)
        self.rsi_period = 14
        self.rsi_entry_max = 20     # Stricter: Deep oversold (was 22)
        
    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = []
        for sym, data in prices.items():
            price = data['priceUsd']
            active_symbols.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_maxlen)
            self.history[sym].append(price)

        # 2. Check Exits (Primary Goal: Secure Profits)
        exit_signal = self._scan_exits(prices)
        if exit_signal:
            return exit_signal
            
        # 3. Check Entries (Secondary Goal: Sniper Entries)
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(active_symbols, prices)
            if entry_signal:
                return entry_signal
            
        return None

    def _scan_exits(self, prices):
        """
        Scans for exits. STRICTLY enforces non-negative PnL.
        """
        candidates = []
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]['priceUsd']
            entry_price = self.entry_meta[sym]['entry_price']
            entry_tick = self.entry_meta[sym]['entry_tick']
            
            roi = (curr_price - entry_price) / entry_price
            
            # === GUARD RAIL: NO LOSSES ===
            # Even if indicators scream sell, if ROI is negative or barely breakeven, we HOLD.
            # 0.001 (0.1%) buffer covers theoretical fees.
            if roi <= 0.001:
                continue

            # Case A: Standard Profit Target
            if roi >= self.min_roi:
                candidates.append((roi, sym, 'TP_STANDARD'))
                continue
            
            # Case B: Stale Position Liquidation
            # If trade is held long time and is green, accept smaller profit to recycle capital
            ticks_held = self.tick_counter - entry_tick
            if ticks_held > self.stale_threshold and roi >= self.scalp_roi:
                candidates.append((roi, sym, 'TP_STALE_ROTATION'))
                
        # Execute best profit opportunity
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._order(best[1], 'SELL', self.positions[best[1]], best[2])
                
        return None

    def _scan_entries(self, active_symbols, prices):
        """
        Identifies entries. Requires statistical anomaly (Crash).
        """
        candidates = []
        
        for sym in active_symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.bb_period: continue
            
            curr_price = prices[sym]['priceUsd']
            
            # 1. Volatility Filter (Bollinger/Z-Score)
            sma = statistics.mean(hist[-self.bb_period:])
            stdev = statistics.stdev(hist[-self.bb_period:])
            
            if stdev == 0: continue
            z_score = (curr_price - sma) / stdev
            
            # Condition 1: Price must be significantly below mean (Crash)
            if z_score > -self.bb_std_entry:
                continue
            
            # Condition 2: RSI Floor
            # Calculates RSI on the most recent window
            rsi = self._calc_rsi(hist)
            if rsi > self.rsi_entry_max:
                continue
                
            # Condition 3: Velocity Check (Mutation)
            # Ensure we aren't catching a "slow bleed". We want a sharp drop.
            # Compare current price to price 3 ticks ago.
            if len(hist) >= 5:
                lag_price = hist[-4]
                drop_velocity = (curr_price - lag_price) / lag_price
                # If price hasn't dropped by at least 0.5% in 3 ticks, it might be a trap
                if drop_velocity > -0.005: 
                    continue

            # Prioritize the most extreme statistical deviation
            candidates.append((z_score, sym))
                    
        if candidates:
            # Sort by Z-score ascending (most negative z-score = deepest discount)
            candidates.sort(key=lambda x: x[0])
            best_sym = candidates[0][1]
            return self._order(best_sym, 'BUY', self.pos_size, 'ENTRY_DEEP_VAL')
            
        return None

    def _order(self, sym, side, amount, tag):
        if side == 'BUY':
            self.positions[sym] = amount
            # Snapshot entry data for precise ROI calculation
            self.entry_meta[sym] = {
                'entry_price': self.history[sym][-1],
                'entry_tick': self.tick_counter
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                del self.entry_meta[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': [tag]
        }

    def _calc_rsi(self, data):
        """Calculates RSI efficiently for the required period"""
        lookback = self.rsi_period
        if len(data) <= lookback:
            return 50
            
        # Analyze only the relevant tail
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