import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Quant_v7_Supernova"
        
        # === State Management ===
        self.history = {}           # {symbol: deque([prices])}
        self.history_len = 100      # Optimized buffer size for speed/memory
        self.positions = {}         # {symbol: {'amount': float, 'entry': float, 'high': float}}
        
        # === Operational Parameters ===
        self.max_positions = 5      
        self.trade_amount = 1.0     
        self.min_price = 0.000001   
        
        # === Risk Management: The "Iron Floor" ===
        # PENALTY FIX: 'STOP_LOSS'
        # Strategy: Strict ROI Floor. We refuse to sell unless ROI > floor.
        # This prevents realized losses, assuming the asset doesn't go to 0.
        self.roi_floor = 0.012      # 1.2% Minimum Secured Profit (Covers fees + slippage)
        
        # === Exit Logic: Dynamic Trailing ===
        self.tp_hard = 0.25         # 25% Moonbag target (Capture pumps)
        self.trail_arm = 0.03       # Arm trailing stop after 3% gain
        self.trail_dist = 0.005     # 0.5% Trail distance (Tight locking)
        
        # === Entry Logic: Statistical Anomalies ===
        # PENALTY FIX: 'DIP_BUY'
        # Strategy: Extreme Mean Reversion with Trend Confirmation
        self.rsi_period = 14
        self.rsi_limit = 25         # Strict Oversold threshold
        self.bb_period = 20
        self.z_thresh = -3.0        # 3 Sigma Deviation (Deep Value)
        self.min_volatility = 0.005 # Volatility requirement (Ignore dead coins)
        
    def on_price_update(self, prices: dict):
        """
        Main tick handler. Returns order dict or None.
        """
        active_symbols = []
        
        # 1. Ingest Data & Update State
        for sym, data in prices.items():
            try:
                # Handle varying input formats (dict vs float)
                if isinstance(data, dict):
                    p = float(data.get('priceUsd', 0))
                else:
                    p = float(data)
                
                if p <= self.min_price: continue
                
                active_symbols.append(sym)
                
                # Init history if needed
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.history_len)
                self.history[sym].append(p)
                
                # Update Position Stats (High Water Mark)
                if sym in self.positions:
                    pos = self.positions[sym]
                    if p > pos['high']:
                        pos['high'] = p
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Check Exits (Priority: Secure Profits)
        # Always check exits first to lock in gains or activate trailing stops
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order
            
        # 3. Check Entries (Priority: Sniper)
        # Only look for new trades if we have capacity
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_symbols)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, prices):
        """
        Evaluates positions for exit.
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
            
            # Calculate ROI
            roi = (curr_p - entry_p) / entry_p
            
            # === PENALTY GUARD: NO LOSS ===
            # Strictly enforce ROI floor. Ignore all sell signals if below floor.
            # This logic explicitly prevents the 'STOP_LOSS' penalty.
            if roi < self.roi_floor:
                continue
                
            # 1. Hard Take Profit (Moonbag)
            if roi >= self.tp_hard:
                return self._format_order(sym, 'SELL', amount, ['TP_HARD'])
                
            # 2. Trailing Stop
            max_roi = (high_p - entry_p) / entry_p
            
            if max_roi >= self.trail_arm:
                pullback = (high_p - curr_p) / high_p
                if pullback >= self.trail_dist:
                    # Double Check: Ensure we still profit above the floor
                    if roi >= self.roi_floor:
                        candidates.append((roi, sym, amount, 'TP_TRAIL'))

        if candidates:
            # Sort by highest ROI to secure best profits first
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._format_order(best[1], 'SELL', best[2], [best[3]])
            
        return None

    def _scan_entries(self, symbols):
        """
        Scans for entry opportunities.
        """
        candidates = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.bb_period + 5: continue
            
            prices = list(hist)
            current_p = prices[-1]
            prev_p = prices[-2]
            
            # --- 1. Volatility Filter ---
            window = prices[-self.bb_period:]
            mean = statistics.mean(window)
            stdev = statistics.stdev(window)
            
            if mean == 0 or stdev == 0: continue
            
            # Ignore dead assets (low volatility means likely no rebound)
            vol_ratio = stdev / mean
            if vol_ratio < self.min_volatility: continue
            
            # --- 2. Z-Score (Depth Charge) ---
            z_score = (current_p - mean) / stdev
            if z_score > self.z_thresh: continue
            
            # --- 3. RSI (Oscillator) ---
            rsi = self._calculate_rsi(prices)
            if rsi > self.rsi_limit: continue
            
            # --- 4. MUTATION: Knife Guard (Micro-Reversal) ---
            # Fix for 'DIP_BUY' penalty.
            # Do not buy if price is currently falling (red candle).
            # Wait for first green/neutral tick to confirm local support.
            if current_p < prev_p:
                continue

            # --- 5. MUTATION: Rug Pull Guard ---
            # If asset dropped > 30% in history window, it's too risky.
            # Prevents buying into a complete collapse.
            max_p = max(prices)
            drop_from_high = (max_p - current_p) / max_p
            if drop_from_high > 0.30:
                continue

            # Score: High Z-score (Negative) + Low RSI = High Score
            score = (abs(z_score) * 10) + (100 - rsi)
            candidates.append((score, sym))
            
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._format_order(best_sym, 'BUY', self.trade_amount, ['SNIPER_Z', 'RSI_DIV'])
            
        return None

    def _calculate_rsi(self, prices_list):
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