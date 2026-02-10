import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Quant_v2"
        
        # === State Management ===
        self.history = {}           # {symbol: deque([prices])}
        self.history_len = 60       # Increased buffer for stability
        self.positions = {}         # {symbol: {'amount': float, 'entry': float, 'high': float}}
        
        # === Operational Parameters ===
        self.max_positions = 5
        self.trade_amount = 1.0     # Fixed trade size
        
        # === Risk Management (NO STOP LOSS) ===
        # Hive Mind Constraint: We never sell for a loss.
        # We enforce a strict minimum ROI (Return on Investment) floor.
        # 0.008 = 0.8% minimum profit (covers fees + spread + profit).
        self.roi_floor = 0.008
        
        # === Exit Logic (Profit Taking) ===
        self.tp_hard = 0.08         # 8% Hard target (Moonbag)
        self.trail_arm = 0.02       # Arm trailing stop at 2% profit
        self.trail_dist = 0.005     # Trail distance 0.5%
        
        # === Entry Logic (Sniper) ===
        # Stricter conditions to avoid catching falling knives.
        self.rsi_period = 14
        self.rsi_limit = 20         # Ultra-deep oversold (RSI < 20)
        self.bb_period = 20
        self.z_threshold = -3.5     # 3.5 Std Devs from mean (Rare event)
        self.min_volatility = 0.003 # Ignore stablecoins/dead assets

    def on_price_update(self, prices: dict):
        """
        Main strategy loop triggered by price updates.
        """
        active_symbols = []
        
        # 1. Ingest Data & Update State
        for sym, data in prices.items():
            try:
                # Parse price safely
                if isinstance(data, dict):
                    p = float(data.get('priceUsd', 0))
                else:
                    p = float(data)
                
                if p <= 0: continue
                
                active_symbols.append(sym)
                
                # Update history buffer
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.history_len)
                self.history[sym].append(p)
                
                # Update High Water Mark for held positions (for trailing stop)
                if sym in self.positions:
                    if p > self.positions[sym]['high']:
                        self.positions[sym]['high'] = p
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Priority 1: Manage Exits (Secure Profits)
        # Check exits first to free up capital.
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order
            
        # 3. Priority 2: Scan Entries (Deploy Capital)
        # Only scan if we have open slots.
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_symbols)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, prices):
        """
        Determines if any position should be sold based on strict ROI rules.
        """
        candidates = []
        
        for sym, pos in self.positions.items():
            # Get current price
            if sym in prices and isinstance(prices[sym], dict):
                curr_p = float(prices[sym]['priceUsd'])
            elif sym in prices:
                curr_p = float(prices[sym])
            else:
                continue
            
            entry_p = pos['entry']
            high_p = pos['high']
            amount = pos['amount']
            
            # Calculate current ROI
            roi = (curr_p - entry_p) / entry_p
            
            # --- CRITICAL: STOP LOSS PROTECTION ---
            # If ROI is below the floor, we hold. No exceptions.
            if roi < self.roi_floor:
                continue
                
            # Logic A: Hard Take Profit
            # If we hit the moon target, sell immediately.
            if roi >= self.tp_hard:
                return self._format_order(sym, 'SELL', amount, ['TP_HARD'])
                
            # Logic B: Trailing Stop
            # Calculate maximum ROI achieved so far
            max_roi = (high_p - entry_p) / entry_p
            
            if max_roi >= self.trail_arm:
                # Calculate pullback from the session high
                pullback = (high_p - curr_p) / high_p
                
                if pullback >= self.trail_dist:
                    # Double-check we are still above the floor (redundant but safe)
                    if roi >= self.roi_floor:
                        candidates.append((roi, sym, amount, 'TP_TRAIL'))

        if candidates:
            # Sort by ROI descending to lock in the most profitable trade first
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._format_order(best[1], 'SELL', best[2], [best[3]])
            
        return None

    def _scan_entries(self, symbols):
        """
        Scans for statistical anomalies (deep dips).
        """
        candidates = []
        
        for sym in symbols:
            # Skip if already held
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.history_len: continue
            
            # Analyze recent window
            recent = list(hist)[-self.bb_period:]
            current_p = recent[-1]
            
            # 1. Volatility Filter
            # Calculate Mean and StdDev
            mean = statistics.mean(recent)
            stdev = statistics.stdev(recent)
            
            if mean == 0: continue
            
            vol_ratio = stdev / mean
            if vol_ratio < self.min_volatility: continue
            
            # 2. Z-Score Deviation (Statistical Reversion)
            if stdev == 0: continue
            z_score = (current_p - mean) / stdev
            
            # Adaptive Threshold: Require deeper dips for higher volatility
            required_z = self.z_threshold
            if vol_ratio > 0.01:
                required_z -= 0.5 # Shift to -4.0 for volatile assets
                
            if z_score > required_z: continue
            
            # 3. RSI Filter (Momentum)
            rsi = self._calculate_rsi(hist)
            if rsi > self.rsi_limit: continue
            
            # 4. Scoring Algorithm
            # Score = Deviation Depth + RSI Oversold magnitude
            # We want the most extreme negative Z-score and lowest RSI
            score = abs(z_score) + (100 - rsi)
            candidates.append((score, sym))
            
        if candidates:
            # Pick the highest scoring anomaly
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._format_order(best_sym, 'BUY', self.trade_amount, ['ENTRY_SNIPER'])
            
        return None

    def _calculate_rsi(self, hist):
        """
        Calculates RSI using Wilder's Smoothing for smoother signals.
        """
        prices = list(hist)[-(self.rsi_period + 1):]
        if len(prices) < self.rsi_period + 1: return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))
        
        # Initial SMA
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0: return 100.0
        if avg_gain == 0: return 0.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _format_order(self, sym, side, amount, reasons):
        """
        Formats the return object and ensures internal state consistency.
        """
        if side == 'BUY':
            # Lock entry price
            price = self.history[sym][-1]
            self.positions[sym] = {
                'amount': amount,
                'entry': price,
                'high': price
            }
        elif side == 'SELL':
            # clear position
            if sym in self.positions:
                del self.positions[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': reasons
        }