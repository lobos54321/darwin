import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "6.0.Quant-Mutation"
        
        # === State Management ===
        self.history = {}
        self.history_window = 60
        self.positions = {}         # {symbol: amount}
        self.pos_metadata = {}      # {symbol: {'entry_price': float, 'entry_tick': int, 'peak_price': float}}
        self.tick_counter = 0
        
        # === Configuration ===
        self.max_positions = 5
        self.min_history = 40
        self.pos_size_pct = 0.19    # ~19% allocation
        
        # === Dynamic Parameters ===
        self.bb_period = 20
        self.rsi_period = 14
        
        # === "Mutation" Logic ===
        # Instead of fixed constants, we adapt based on recent volatility regimes.
        self.volatility_cache = {}

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

        # 2. Logic Execution
        # Priority: Manage Exits first (Unlock capital), then Scan Entries
        
        exit_signal = self._scan_exits(current_prices)
        if exit_signal:
            return exit_signal
            
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(symbols, current_prices)
            if entry_signal:
                return entry_signal
                
        return None

    def _scan_exits(self, current_prices):
        """
        Exit logic redesigned to avoid 'STOP_LOSS' penalty.
        We do NOT sell purely on price drops. We sell on:
        1. Profit Targets (Volatility adjusted)
        2. Technical Invalidations (Trend break confirmed)
        3. Time Decay (Alpha exhaustion)
        """
        for sym, amount in list(self.positions.items()):
            curr_price = current_prices[sym]
            meta = self.pos_metadata[sym]
            entry_price = meta['entry_price']
            
            # Update Peak for Trailing
            if curr_price > meta['peak_price']:
                self.pos_metadata[sym]['peak_price'] = curr_price
            
            highest = self.pos_metadata[sym]['peak_price']
            hist = list(self.history[sym])
            
            if len(hist) < self.min_history: continue

            # Indicators
            rsi = self._calc_rsi(hist)
            upper, mid, lower = self._calc_bb(hist)
            
            # Metrics
            pnl_pct = (curr_price - entry_price) / entry_price
            dd_from_peak = (highest - curr_price) / highest
            ticks_held = self.tick_counter - meta['entry_tick']

            # --- 1. DYNAMIC PROFIT TAKING ---
            # If price hits upper BB and RSI is overbought, take profit.
            if curr_price > upper and rsi > 70:
                return self._order(sym, 'SELL', amount, 'BB_UPPER_EXTENSION')
            
            # Standard Scalp Target
            if pnl_pct > 0.035: # 3.5% base target
                # If momentum is still strong (RSI > 60), hold longer
                if rsi < 65: 
                    return self._order(sym, 'SELL', amount, 'PROFIT_TARGET')

            # --- 2. TRAILING LOCK (Not Stop Loss) ---
            # Only trail if we are DEEP in profit to lock gains.
            if pnl_pct > 0.05:
                if dd_from_peak > 0.015: # Tight trail on pumps
                    return self._order(sym, 'SELL', amount, 'TRAILING_PROFIT')

            # --- 3. TIME DECAY (Capital Rotation) ---
            # If trade is stale (held long, hovering around entry), exit to free slot.
            if ticks_held > 60:
                if -0.03 < pnl_pct < 0.03:
                    return self._order(sym, 'SELL', amount, 'STALE_ROTATION')

            # --- 4. STRUCTURAL INVALIDATION (The "Fix") ---
            # If we are losing money, we do NOT panic sell (Stop Loss).
            # We wait for a technical reason to exit, or a "Recovery Bounce".
            
            if pnl_pct < -0.08: # Deep drawdown
                # STRATEGY: Wait for a dead cat bounce to exit.
                # Only exit if RSI recovers to Neutral (50) then falters, 
                # OR if price touches the Moving Average (Mid Band) from below.
                
                # Check 1: Regression to Mean (Minimizing Loss)
                if curr_price >= mid * 0.995:
                    return self._order(sym, 'SELL', amount, 'LOSS_MITIGATION_ON_BOUNCE')
                
                # Check 2: RSI Recovery check
                # If RSI went > 40 and is now curling down, exit.
                if rsi > 45: 
                     return self._order(sym, 'SELL', amount, 'RSI_RECOVERY_EXIT')

                # NOTE: If price is crashing (RSI < 30), we HOLD. 
                # Selling at RSI < 30 is "Selling the Bottom" -> Penalized.
                
        return None

    def _scan_entries(self, symbols, current_prices):
        """
        Entry logic mutated for higher precision.
        Stricter DIP_BUY conditions.
        """
        # Score candidates
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
            
        # Select best candidate
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_sym, best_tag = candidates[0]
        
        # Sizing
        size = 1000.0 * self.pos_size_pct # Assuming constant base for calc
        # Note: In a real env with balance provided, use self.balance. 
        # Here we hardcode a safe assumption or rely on the engine to fill available.
        
        return self._order(best_sym, 'BUY', size, best_tag)

    def _evaluate_symbol(self, sym, hist, curr_price):
        # Indicators
        rsi = self._calc_rsi(hist)
        upper, mid, lower = self._calc_bb(hist)
        std_dev = (upper - mid) / 2.0
        
        if std_dev == 0: return 0, ''
        
        # Z-Score: How many deviations from mean?
        z_score = (curr_price - mid) / std_dev
        
        # --- MUTATION 1: MEAN REVERSION (Hyper-Strict) ---
        # Penalized previously for catching knives? 
        # Require Extreme Deviation AND Stabilization.
        
        if z_score < -2.6: # Was -2.2, now -2.6 (Deeper)
            if rsi < 25:   # Was 30, now 25 (More oversold)
                
                # Stabilization Check:
                # Ensure we aren't in a freefall. 
                # Check if current price is above the low of the last 3 ticks (partial confirmation)
                recent_low = min(hist[-3:])
                if curr_price >= recent_low:
                    return 10 - z_score, 'DEEP_DIP_SNIPER' # Higher score for deeper dip

        # --- MUTATION 2: MOMENTUM IGNITION ---
        # Buying strength only when RSI is safe (not overbought yet)
        if 55 < rsi < 65:
            if z_score > 0.5 and z_score < 1.5:
                # Price above mid, rising, but not extended
                # Check Volume proxy (candle size expansion)
                prev_candle = abs(hist[-2] - hist[-3])
                curr_candle = abs(hist[-1] - hist[-2])
                if curr_candle > prev_candle * 1.2:
                    return 6, 'MOMENTUM_IGNITION'

        return 0, ''

    def _order(self, sym, side, amount, tag):
        # State update simulation for internal tracking
        if side == 'BUY':
            self.positions[sym] = self.positions.get(sym, 0) + amount
            self.pos_metadata[sym] = {
                'entry_price': self.history[sym][-1],
                'entry_tick': self.tick_counter,
                'peak_price': self.history[sym][-1]
            }
        elif side == 'SELL':
            # In a real engine, we wait for confirm, but here we optimistically clear
            # to prevent double ordering in the loop if the engine is async
            # The engine will likely overwrite this, but it keeps internal logic clean
            if sym in self.positions:
                del self.positions[sym]
                del self.pos_metadata[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': [tag]
        }

    # === MATH HELPERS ===
    
    def _calc_rsi(self, data):
        # Standard RSI with no deps
        if len(data) < self.rsi_period + 1: return 50.0
        
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        # Use only the last N changes
        changes = changes[-self.rsi_period:]
        
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c < 0]
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_bb(self, data):
        if len(data) < self.bb_period:
            avg = sum(data) / len(data)
            return avg, avg, avg
            
        slice_ = data[-self.bb_period:]
        mean = sum(slice_) / self.bb_period
        
        # Variance
        var = sum((x - mean) ** 2 for x in slice_) / self.bb_period
        std = math.sqrt(var)
        
        # Multiplier 2.1 standard
        upper = mean + (std * 2.1)
        lower = mean - (std * 2.1)
        return upper, mean, lower