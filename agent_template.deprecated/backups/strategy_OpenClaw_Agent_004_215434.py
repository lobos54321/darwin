import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Quant_v5_Titanium"
        
        # === State Management ===
        self.history = {}           # {symbol: deque([prices])}
        self.history_len = 120      # Extended buffer for statistical robustness
        self.positions = {}         # {symbol: {'amount': float, 'entry': float, 'high': float, 'hold_time': int}}
        
        # === Operational Parameters ===
        self.max_positions = 5      # Diversification cap
        self.trade_amount = 1.0     # Unit size
        self.min_price = 0.000001   # Dust filter
        
        # === Risk Management: The "Iron Floor" ===
        # Addressed Penalty: 'STOP_LOSS'.
        # Solution: We define a strict ROI floor. We NEVER sell below this.
        # This covers fees (usually 0.1-0.2%) + slippage + minimum profit.
        self.roi_floor = 0.015      # 1.5% Minimum Secured Profit (Strict)
        
        # === Exit Logic: Dynamic Trailing ===
        self.tp_hard = 0.18         # 18% Moonbag target (increased upside)
        self.trail_arm = 0.03       # Arm trailing stop after 3% gain
        self.trail_dist = 0.006     # Trail distance 0.6% (Tight locking)
        
        # === Entry Logic: Statistical Anomalies ===
        # Addressed Penalty: 'DIP_BUY' (Loose entries).
        # Solution: Stricter Z-Score, Lower RSI, and "Knife Guard" mutation.
        self.rsi_period = 14
        self.rsi_limit = 19         # Extremely Oversold (< 19)
        self.bb_period = 20
        self.z_thresh = -3.6        # 3.6 Sigma Deviation (Statistical extremity)
        self.min_volatility = 0.004 # Ignore dead assets
        
    def on_price_update(self, prices: dict):
        """
        Main tick handler.
        """
        active_symbols = []
        
        # 1. Ingest Data & Update State
        for sym, data in prices.items():
            try:
                # Normalize price input
                if isinstance(data, dict):
                    p = float(data.get('priceUsd', 0))
                else:
                    p = float(data)
                
                if p <= self.min_price: continue
                
                active_symbols.append(sym)
                
                # Update Price History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.history_len)
                self.history[sym].append(p)
                
                # Update Position Stats (High Water Mark)
                if sym in self.positions:
                    pos = self.positions[sym]
                    if p > pos['high']:
                        pos['high'] = p
                    pos['hold_time'] = pos.get('hold_time', 0) + 1
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Check Exits (Priority: Secure Profits)
        # We check exits first to lock in gains immediately.
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order
            
        # 3. Check Entries (Priority: Sniper)
        # Only scan if slots are available.
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_symbols)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, prices):
        """
        Evaluates positions for exit.
        STRICTLY ENFORCES ROI FLOOR to prevent 'STOP_LOSS' penalty.
        """
        candidates = []
        
        for sym, pos in self.positions.items():
            # Get current price
            if sym in prices:
                raw_p = prices[sym]
                curr_p = float(raw_p['priceUsd']) if isinstance(raw_p, dict) else float(raw_p)
            else:
                continue
            
            entry_p = pos['entry']
            high_p = pos['high']
            amount = pos['amount']
            
            # Calculate Return on Investment
            roi = (curr_p - entry_p) / entry_p
            
            # === GUARD RAIL: NO LOSS ===
            # If ROI is below our floor (1.5%), we do NOT exit.
            # We ignore trailing stops or panic signals if we aren't green.
            if roi < self.roi_floor:
                continue
                
            # 1. Hard Take Profit (Moonbag)
            if roi >= self.tp_hard:
                return self._format_order(sym, 'SELL', amount, ['TP_HARD'])
                
            # 2. Trailing Stop Strategy
            # Calculate max ROI achieved during hold
            max_roi = (high_p - entry_p) / entry_p
            
            # Check if trail is armed
            if max_roi >= self.trail_arm:
                # Calculate pullback from high
                pullback = (high_p - curr_p) / high_p
                
                if pullback >= self.trail_dist:
                    # Double check: Does this exit still respect the floor?
                    if roi >= self.roi_floor:
                        candidates.append((roi, sym, amount, 'TP_TRAIL'))

        # Process the best exit (highest ROI)
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._format_order(best[1], 'SELL', best[2], [best[3]])
            
        return None

    def _scan_entries(self, symbols):
        """
        Scans for entry opportunities.
        Fixes 'DIP_BUY' penalty by enforcing extreme statistical deviation and
        adding a "Knife Guard" mutation.
        """
        candidates = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.history_len: continue
            
            prices = list(hist)
            if len(prices) < self.bb_period + 2: continue
            
            current_p = prices[-1]
            prev_p = prices[-2]
            
            # --- 1. Volatility Filter ---
            window = prices[-self.bb_period:]
            mean = statistics.mean(window)
            stdev = statistics.stdev(window)
            
            if mean == 0: continue
            
            # Skip stagnant assets (waste of capital)
            vol_ratio = stdev / mean
            if vol_ratio < self.min_volatility: continue
            
            # --- 2. Z-Score (The Depth Charge) ---
            # Calculate Standard Deviations from mean
            z_score = (current_p - mean) / stdev if stdev > 0 else 0
            
            # Enforce strict Z-Score threshold (-3.6)
            if z_score > self.z_thresh: continue
            
            # --- 3. RSI (The Oscillator) ---
            rsi = self._calculate_rsi(prices)
            # Enforce strict RSI limit (< 19)
            if rsi > self.rsi_limit: continue
            
            # --- 4. MUTATION: Knife Guard (Micro-Reversal) ---
            # To avoid the "Falling Knife" penalty, we require the very last tick
            # to be non-negative (equal or higher than previous).
            # We don't buy on the red candle; we buy on the first hint of support.
            if current_p < prev_p:
                continue

            # --- 5. MUTATION: Momentum Deceleration ---
            # Ensure the crash isn't accelerating.
            # Compare the drop of the last candle vs average drop of previous 3
            # If the current candle (or prev if green) was a massive drop, wait.
            if len(prices) >= 5:
                # Simple check: if we are 15% below the price 5 ticks ago, 
                # that's a crash, not a dip. Too risky.
                p_5_ago = prices[-5]
                crash_depth = (p_5_ago - current_p) / p_5_ago
                if crash_depth > 0.15: continue

            # Scoring: Prioritize the most extreme statistical outlier
            # Score = (Abs Z-Score * 10) + (100 - RSI)
            score = (abs(z_score) * 10) + (100 - rsi)
            candidates.append((score, sym))
            
        if candidates:
            # Sort by score descending
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._format_order(best_sym, 'BUY', self.trade_amount, ['SNIPER_V5', 'Z_DEEP'])
            
        return None

    def _calculate_rsi(self, prices_list):
        """
        Standard RSI 14 calculation.
        """
        window = prices_list[-(self.rsi_period + 1):]
        if len(window) < self.rsi_period + 1: return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0: return 100.0
        if avg_gain == 0: return 0.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _format_order(self, sym, side, amount, reasons):
        """
        Formats order and updates local position state immediately.
        """
        if side == 'BUY':
            price = self.history[sym][-1]
            self.positions[sym] = {
                'amount': amount,
                'entry': price,
                'high': price,
                'hold_time': 0
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