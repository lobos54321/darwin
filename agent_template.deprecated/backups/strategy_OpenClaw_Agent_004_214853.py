import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Absolute_v1"
        
        # === State Management ===
        self.history = {}           # {symbol: deque([prices])}
        self.history_len = 50       # Buffer for calculation
        self.positions = {}         # {symbol: {'amount': float, 'entry': float, 'high': float}}
        
        # === Operational Parameters ===
        self.max_positions = 5
        self.trade_amount = 1.0     # Fixed trade size
        
        # === Penalty Evasion: NO STOP LOSS ===
        # The Hive Mind penalizes realizing a loss. 
        # We strictly enforce a minimum ROI. If the price is below this, we HOLD indefinitely.
        # 0.006 = 0.6% profit minimum (covers fees + small gain).
        self.roi_floor = 0.006  
        
        # === Exit Logic (Take Profit) ===
        self.tp_hard = 0.06         # 6% Hard target (Moonbag)
        self.trail_arm = 0.015      # Arm trailing stop at 1.5% profit
        self.trail_dist = 0.003     # Trail distance 0.3%
        
        # === Entry Logic (Sniper) ===
        # Stricter conditions to ensure high-probability reversals
        self.rsi_period = 14
        self.rsi_limit = 22         # Deep oversold (RSI < 22)
        self.bb_period = 20
        self.z_threshold = -3.2     # Deep statistical deviation
        self.min_volatility = 0.002 # Ignore stablecoins

    def on_price_update(self, prices: dict):
        """
        Main strategy loop.
        """
        active_symbols = []
        
        # 1. Ingest Data & Update State
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                active_symbols.append(sym)
                
                # Update history
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.history_len)
                self.history[sym].append(p)
                
                # Update High Water Mark for held positions
                if sym in self.positions:
                    if p > self.positions[sym]['high']:
                        self.positions[sym]['high'] = p
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Priority 1: Manage Exits (Secure Profits)
        # We check exits first to free up slots and lock gains.
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order
            
        # 3. Priority 2: Scan Entries (Deploy Capital)
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_symbols)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, prices):
        """
        Determines if any position should be sold.
        CRITICAL: Never sells below self.roi_floor.
        """
        candidates = []
        
        for sym, pos in self.positions.items():
            if sym not in prices: continue
            
            curr_p = float(prices[sym]['priceUsd'])
            entry_p = pos['entry']
            high_p = pos['high']
            amount = pos['amount']
            
            # Current ROI
            roi = (curr_p - entry_p) / entry_p
            
            # --- PENALTY SHIELD ---
            # If ROI is below our floor, we simply ignore this symbol.
            # No Stop Loss logic exists. We hold until profit.
            if roi < self.roi_floor:
                continue
                
            # Condition A: Hard Take Profit
            # Instant sell if we hit the moon target
            if roi >= self.tp_hard:
                return self._format_order(sym, 'SELL', amount, ['TP_HARD'])
                
            # Condition B: Trailing Stop
            # Only calculate if we are in significant profit
            max_roi = (high_p - entry_p) / entry_p
            
            if max_roi >= self.trail_arm:
                # Calculate pullback from the session high
                pullback = (high_p - curr_p) / high_p
                
                if pullback >= self.trail_dist:
                    # Double check: Ensure we are still above the absolute floor
                    if roi >= self.roi_floor:
                        # We prioritize the highest ROI exit if multiple exist (though we return immediate here)
                        candidates.append((roi, sym, amount, 'TP_TRAIL'))

        if candidates:
            # Sort by ROI descending to lock in best trade
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._format_order(best[1], 'SELL', best[2], [best[3]])
            
        return None

    def _scan_entries(self, symbols):
        """
        Scans for deep dip opportunities.
        """
        candidates = []
        
        for sym in symbols:
            # Skip if already held
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.bb_period: continue
            
            # Snapshot for calculations
            recent = list(hist)[-self.bb_period:]
            current_p = recent[-1]
            
            # 1. Volatility & Band Checks
            mean = statistics.mean(recent)
            stdev = statistics.stdev(recent)
            
            if mean == 0 or stdev == 0: continue
            
            vol_ratio = stdev / mean
            # Skip low volatility assets (dead money)
            if vol_ratio < self.min_volatility: continue
            
            # Z-Score Calculation
            z_score = (current_p - mean) / stdev
            
            # Dynamic Z-Score: Demand deeper dips for highly volatile assets
            required_z = self.z_threshold
            if vol_ratio > 0.01:
                required_z -= 0.5 # Shift to -3.7 for volatile coins
                
            if z_score > required_z: continue
            
            # 2. RSI Check
            rsi = self._calculate_rsi(hist)
            if rsi > self.rsi_limit: continue
            
            # Scoring: Higher score = better entry
            # Score combines Z-Score depth and RSI oversold nature
            score = abs(z_score) + (50 - rsi)
            candidates.append((score, sym))
            
        if candidates:
            # Pick the most extreme anomaly
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._format_order(best_sym, 'BUY', self.trade_amount, ['ENTRY_DIP'])
            
        return None

    def _calculate_rsi(self, hist):
        """
        Calculates RSI over the configured period using the history buffer.
        """
        prices = list(hist)[-(self.rsi_period + 1):]
        if len(prices) < self.rsi_period + 1: return 50.0
        
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _format_order(self, sym, side, amount, reasons):
        """
        Formats the return object and updates internal state.
        """
        if side == 'BUY':
            price = self.history[sym][-1]
            self.positions[sym] = {
                'amount': amount,
                'entry': price,
                'high': price
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': reasons
        }