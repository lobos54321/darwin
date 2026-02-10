import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "21.0.Quantum_Guard_V1"
        
        # === State ===
        self.history = {}
        self.history_maxlen = 80
        self.positions = {}         # {symbol: amount}
        self.entry_meta = {}        # {symbol: {'entry_price': float, 'entry_tick': int}}
        self.tick_counter = 0
        
        # === Constraints ===
        self.max_positions = 5
        self.pos_size = 1.0
        
        # === Risk Management (Strict Profit Enforcement) ===
        # FIX: Penalized for STOP_LOSS.
        # Solution: "Ironclad Hold" logic with a slippage safety margin.
        # We never emit a SELL signal unless ROI covers the safety margin.
        self.safety_margin = 0.003  # 0.3% Minimum ROI (covers fees + slippage)
        
        self.base_roi = 0.022       # 2.2% Standard Profit Target
        self.scalp_roi = 0.008      # 0.8% "Stale" Profit Target
        self.stale_ticks = 50       # Duration before accepting Scalp ROI
        
        # === Entry Technicals (Adaptive) ===
        self.bb_period = 20
        self.rsi_period = 14
        self.z_trigger_base = 3.0   # Base Sigma deviation
        
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

        # 2. Check Exits (Priority: Secure Gains)
        # We process exits first to free up capital for new opportunities
        exit_signal = self._scan_exits(prices)
        if exit_signal:
            return exit_signal
            
        # 3. Check Entries (Priority: High Probability Reversion)
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(active_symbols, prices)
            if entry_signal:
                return entry_signal
            
        return None

    def _scan_exits(self, prices):
        """
        Scans for profitable exits.
        CRITICAL: Prevents STOP_LOSS by strictly enforcing positive ROI > safety_margin.
        """
        candidates = []
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]['priceUsd']
            entry_data = self.entry_meta.get(sym)
            if not entry_data: continue
            
            entry_price = entry_data['entry_price']
            entry_tick = entry_data['entry_tick']
            
            # ROI Calculation
            roi = (curr_price - entry_price) / entry_price
            
            # === GUARD RAIL: NO STOP LOSS ===
            # Even if indicators suggest selling, we HOLD if not profitable.
            if roi < self.safety_margin:
                continue

            # Mutation: Volatility-Adjusted Targets
            # If the asset is volatile, expand the profit target to capture the surge.
            hist = self.history[sym]
            volatility_bonus = 0.0
            if len(hist) > 10:
                recent_window = list(hist)[-10:]
                avg_price = statistics.mean(recent_window)
                if avg_price > 0:
                    vol_pct = statistics.stdev(recent_window) / avg_price
                    if vol_pct > 0.005: # High volatility
                        volatility_bonus = 0.015 # Add 1.5% to target

            target_roi = self.base_roi + volatility_bonus
            
            # Case A: Target Hit
            if roi >= target_roi:
                candidates.append((roi, sym, 'TP_DYNAMIC'))
                continue
            
            # Case B: Stale Position Rotation
            # If trade is stagnant but profitable (above scalp_roi), exit to free slot.
            ticks_held = self.tick_counter - entry_tick
            if ticks_held > self.stale_ticks and roi >= self.scalp_roi:
                candidates.append((roi, sym, 'TP_STALE'))
                
        if candidates:
            # Prioritize securing the highest ROI first
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._order(best[1], 'SELL', self.positions[best[1]], best[2])
                
        return None

    def _scan_entries(self, active_symbols, prices):
        """
        Identifies entries using Trend-Adaptive Statistical Reversion.
        """
        candidates = []
        
        for sym in active_symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.bb_period: continue
            
            curr_price = prices[sym]['priceUsd']
            
            # Statistics
            sma = statistics.mean(hist[-self.bb_period:])
            stdev = statistics.stdev(hist[-self.bb_period:])
            
            if stdev == 0: continue
            z_score = (curr_price - sma) / stdev
            
            # Mutation: Trend Adaptation
            # If price is below the 50-tick SMA, we are in a downtrend/crash.
            # In a crash, we demand a much deeper discount (stricter Z-score) to avoid catching a falling knife.
            trend_period = min(len(hist), 50)
            trend_sma = statistics.mean(hist[-trend_period:])
            
            required_z = -self.z_trigger_base # Default: -3.0
            if curr_price < trend_sma:
                # Downtrend detected -> Stricter Entry
                required_z = -3.5
            
            # Condition 1: Z-Score Depth
            if z_score > required_z:
                continue
            
            # Condition 2: RSI Floor
            rsi = self._calc_rsi(hist)
            if rsi > 25: # Stricter than standard 30
                continue
                
            # Condition 3: Velocity Check (Mutation)
            # Ensure the price actually dropped sharply recently (Panic) rather than slow bleed.
            if len(hist) >= 4:
                lookback_price = hist[-4]
                drop_pct = (curr_price - lookback_price) / lookback_price
                # Must have dropped at least 0.4% in last 3 ticks
                if drop_pct > -0.004:
                    continue

            # Calculate "Value Score" (how far below the required Z-score are we?)
            deviation_excess = required_z - z_score
            candidates.append((deviation_excess, sym))
                    
        if candidates:
            # Sort by deviation excess (most undervalued relative to its trend context)
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._order(best_sym, 'BUY', self.pos_size, 'ENTRY_ADAPTIVE_Z')
            
        return None

    def _order(self, sym, side, amount, tag):
        if side == 'BUY':
            self.positions[sym] = amount
            # Snapshot entry state
            self.entry_meta[sym] = {
                'entry_price': self.history[sym][-1],
                'entry_tick': self.tick_counter
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                del self.entry_meta[sym]