import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Quant_v4_IronHand"
        
        # === State Management ===
        self.history = {}           # {symbol: deque([prices])}
        self.history_len = 100      # Increased buffer for EMA/Longer MAs
        self.positions = {}         # {symbol: {'amount': float, 'entry': float, 'high': float, 'hold_time': int}}
        
        # === Operational Parameters ===
        self.max_positions = 5
        self.trade_amount = 1.0     # Fixed trade size
        self.min_price = 0.000001   # Sanity check
        
        # === Risk Management (The "NoLoss" Mandate) ===
        # Hive Mind Constraint: ABSOLUTELY NO SELLING AT LOSS.
        # We enforce a strict ROI floor that covers fees + slippage.
        self.roi_floor = 0.012      # 1.2% Minimum secured profit before any exit consideration
        
        # === Exit Logic (Dynamic Trailing) ===
        self.tp_hard = 0.15         # 15% Moonbag target
        self.trail_arm = 0.03       # Arm trailing stop at 3% profit
        self.trail_dist = 0.008     # Trail distance 0.8%
        
        # === Entry Logic (Sniper Mutation) ===
        # Penalized for loose 'DIP_BUY'. We apply stricter filters.
        self.rsi_period = 14
        self.rsi_limit = 22         # Stricter: Oversold < 22 (was 25)
        self.bb_period = 20
        self.base_z_score = -3.2    # Stricter: 3.2 Sigma (was 3.0)
        self.min_volatility = 0.003 # Filter out stagnant assets
        
        # Uniqueness: EMA Trend Filter
        # Only buy dips that are statistical anomalies, but avoid "falling knives" 
        # that have completely broken long-term structure? 
        # Actually, for HFT, we want mean reversion. 
        # We add a "Velocity Check" to ensure we don't buy the exact moment of a crash.

    def on_price_update(self, prices: dict):
        """
        Main execution loop.
        """
        active_symbols = []
        
        # 1. Ingest Data & Update State
        for sym, data in prices.items():
            try:
                # Robust parsing
                if isinstance(data, dict):
                    p = float(data.get('priceUsd', 0))
                else:
                    p = float(data)
                
                if p <= self.min_price: continue
                
                active_symbols.append(sym)
                
                # History Management
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.history_len)
                self.history[sym].append(p)
                
                # Position Management (High Water Mark)
                if sym in self.positions:
                    pos = self.positions[sym]
                    if p > pos['high']:
                        pos['high'] = p
                    # Track hold duration (cycles)
                    pos['hold_time'] = pos.get('hold_time', 0) + 1
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Check Exits (Priority: Secure Profits)
        # We process exits first to free up slots for new opportunities
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order
            
        # 3. Check Entries (Priority: Sniper Entry)
        # Only scan if we have capital/slots available
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_symbols)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, prices):
        """
        Evaluates positions for exit.
        CRITICAL: Never generates a sell order if ROI < roi_floor.
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
            
            # ROI Calculation
            roi = (curr_p - entry_p) / entry_p
            
            # --- IRON CLAD RULE: NO LOSS ---
            if roi < self.roi_floor:
                # If we are underwater, we HOLD. 
                # No stop loss allowed by Hive Mind.
                continue
                
            # 1. Hard Take Profit (Moonbag)
            if roi >= self.tp_hard:
                return self._format_order(sym, 'SELL', amount, ['TP_HARD', 'MOON'])
                
            # 2. Trailing Stop Strategy
            # Calculate max potential ROI achieved
            max_roi = (high_p - entry_p) / entry_p
            
            # Check if trail is armed
            if max_roi >= self.trail_arm:
                # Calculate pullback from high
                pullback = (high_p - curr_p) / high_p
                
                if pullback >= self.trail_dist:
                    # Final safety check: ensuring the drop didn't breach our floor
                    # This prevents the trailing stop from executing if price crashed instantly
                    if roi >= self.roi_floor:
                        candidates.append((roi, sym, amount, 'TP_TRAIL'))

        # Sort by highest secured ROI to lock in the biggest wins first
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._format_order(best[1], 'SELL', best[2], [best[3]])
            
        return None

    def _scan_entries(self, symbols):
        """
        Scans for entry opportunities.
        Fixes 'DIP_BUY' penalty by enforcing stricter statistical deviation.
        """
        candidates = []
        
        for sym in symbols:
            # Skip if already holding
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.history_len: continue
            
            # Convert to list for slicing
            prices = list(hist)
            
            # Need enough data for BB and RSI
            if len(prices) < max(self.bb_period, self.rsi_period + 1): continue
            
            current_p = prices[-1]
            
            # --- 1. Volatility Context ---
            # Calculate recent volatility (Standard Deviation / Mean)
            recent_window = prices[-self.bb_period:]
            mean = statistics.mean(recent_window)
            stdev = statistics.stdev(recent_window)
            
            if mean == 0: continue
            
            vol_ratio = stdev / mean
            if vol_ratio < self.min_volatility: 
                # Asset is dead/flat, ignore
                continue
                
            # --- 2. Adaptive Z-Score (The Mutation) ---
            # We calculate how many standard deviations price is from mean.
            # We enforce stricter requirements for higher volatility assets to avoid catching knives.
            z_score = (current_p - mean) / stdev if stdev > 0 else 0
            
            # Base requirement: -3.2 sigma
            # Adaptive penalty: If vol is high (e.g. 1%), require deeper dip
            # Formula: required = base - (vol_ratio * multiplier)
            vol_penalty = vol_ratio * 50.0 
            required_z = self.base_z_score - vol_penalty
            
            # Hard clamp to prevent impossible conditions, but cap at -5.0
            required_z = max(required_z, -6.0)
            
            if z_score > required_z: continue
            
            # --- 3. RSI Confirmation ---
            rsi = self._calculate_rsi(prices)
            if rsi > self.rsi_limit: continue
            
            # --- 4. Short-term Momentum Check (Velocity) ---
            # Ensure price isn't free-falling in the last 3 ticks
            # If last 3 ticks are strictly decreasing with accelerating gaps, wait.
            # Simple heuristic: last tick shouldn't be the biggest drop
            if len(prices) >= 3:
                d1 = prices[-2] - prices[-1] # Drop size recent
                d2 = prices[-3] - prices[-2] # Drop size previous
                # If dropping and accelerating (d1 > d2 * 1.5), skip (knife)
                if d1 > 0 and d2 > 0 and d1 > (d2 * 1.5):
                    continue

            # Scoring:
            # Weighted mix of Z-Score depth and RSI oversold nature
            # Higher score = Better buy
            score = abs(z_score) + (50 - rsi)
            candidates.append((score, sym))
            
        if candidates:
            # Pick the most extreme statistical outlier
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._format_order(best_sym, 'BUY', self.trade_amount, ['SNIPER_ENTRY', 'DEEP_Z'])
            
        return None

    def _calculate_rsi(self, prices_list):
        """
        Calculates RSI(14).
        """
        # Slice the required window
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