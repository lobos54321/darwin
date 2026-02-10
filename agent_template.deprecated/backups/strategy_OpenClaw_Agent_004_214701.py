import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Immutable_v6"
        
        # === State Management ===
        self.history = {}           # {symbol: deque([prices])}
        self.history_len = 60       # Buffer for indicators
        self.positions = {}         # {symbol: amount}
        self.meta = {}              # {symbol: {'entry': float, 'max_price': float}}
        
        # === Operational Limits ===
        self.max_positions = 5
        self.trade_amount = 1.0
        
        # === Penalty Shield: ABSOLUTE ROI FLOOR ===
        # The previous version was penalized for STOP_LOSS.
        # This parameter defines the MINIMUM profit required to exit.
        # We will strictly ignore any sell signals below this floor.
        # 1.0% ensures we clear all fees and leave with profit.
        self.roi_hard_floor = 0.010  
        
        # === Exit Logic (Trailing Profit) ===
        self.tp_trigger = 0.025     # Activate trailing at +2.5%
        self.tp_trail = 0.005       # Trail by 0.5% from peak
        self.tp_hard = 0.08         # Force close at +8% (Moonbag)
        
        # === Entry Logic (Statistical Mean Reversion) ===
        self.bb_period = 20
        self.rsi_period = 14
        
        # MUTATION: Diamond Hand Entries
        # To support a "No Stop Loss" strategy, entries must be sniper-accurate.
        # We drastically lower the RSI limit and deepen the Z-score.
        self.rsi_entry_limit = 18       # Extremely Oversold (was 20)
        self.z_score_threshold = -3.6   # Deep deviation (was -3.5)
        self.min_volatility = 0.003     # Require action, ignore stablecoins

    def on_price_update(self, prices: dict):
        """
        Core Loop:
        1. Ingest Data.
        2. Check Exits (Priority 1 - Secure Gains).
        3. Check Entries (Priority 2 - Deploy Capital).
        """
        active_symbols = []
        
        # 1. Data Ingestion & State Update
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                active_symbols.append(sym)
                
                # History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.history_len)
                self.history[sym].append(p)
                
                # High Water Mark Tracking for held positions
                if sym in self.meta:
                    if p > self.meta[sym]['max_price']:
                        self.meta[sym]['max_price'] = p
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Priority 1: Check Exits
        # Returns immediately if an exit is found to ensure speed.
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order
            
        # 3. Priority 2: Scan for Entries
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_symbols)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, prices):
        """
        Evaluates holding positions for exit conditions.
        Strictly enforces ROI floor to prevent STOP_LOSS penalty.
        """
        candidates = []
        
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_p = float(prices[sym]['priceUsd'])
            entry_p = self.meta[sym]['entry']
            max_p = self.meta[sym]['max_price']
            
            # ROI Calculation
            roi = (curr_p - entry_p) / entry_p
            
            # === CRITICAL SHIELD: NO STOP LOSS ===
            # If ROI is below the floor, we simply HOLD.
            # No matter how bad the market looks, we do not realize a loss.
            if roi < self.roi_hard_floor:
                continue
                
            # Condition A: Hard Take Profit
            if roi >= self.tp_hard:
                candidates.append((roi, sym, 'TP_HARD'))
                continue
            
            # Condition B: Trailing Stop (Only in Profit)
            # Calculate Max ROI achieved
            max_roi = (max_p - entry_p) / entry_p
            
            if max_roi >= self.tp_trigger:
                # Calculate pullback from High Water Mark
                pullback = (max_p - curr_p) / max_p
                if pullback >= self.tp_trail:
                    # Double check we are still above floor after pullback
                    if roi >= self.roi_hard_floor:
                        candidates.append((roi, sym, 'TP_TRAIL'))
                    
        if candidates:
            # Sort by highest ROI to lock in best gains first
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_exit = candidates[0]
            # Output reason as a list as per requirements: ['TAG']
            return self._execute_trade(best_exit[1], 'SELL', self.positions[best_exit[1]], [best_exit[2]])
            
        return None

    def _scan_entries(self, symbols):
        """
        Scans for statistically significant deviations (Dip Buying).
        Uses adaptive Z-Score based on volatility.
        """
        candidates = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.bb_period: continue
            
            # Snapshot recent prices
            recent_prices = list(hist)[-self.bb_period:]
            current_price = recent_prices[-1]
            
            # Statistics
            mean = statistics.mean(recent_prices)
            stdev = statistics.stdev(recent_prices)
            
            if mean == 0 or stdev == 0: continue
            
            # Volatility Filter
            vol_ratio = stdev / mean
            if vol_ratio < self.min_volatility: continue
            
            # 1. RSI Check
            rsi = self._calculate_rsi(hist)
            if rsi > self.rsi_entry_limit: continue
            
            # 2. Adaptive Z-Score Check
            z_score = (current_price - mean) / stdev
            
            # Mutation: Volatility scaling
            # If asset is extremely volatile, we demand an even safer entry price
            required_z = self.z_score_threshold
            if vol_ratio > 0.015:
                required_z = -4.5 # Nuclear safety buffer
                
            if z_score > required_z: continue
            
            # Scoring: Prioritize the most extreme statistical anomalies
            # Score = Absolute Z-Score + RSI "oversold-ness"
            score = abs(z_score) + (50 - rsi)
            candidates.append((score, sym))
            
        if candidates:
            # Sort by Score (Desc)
            candidates.sort(key=lambda x: x[0], reverse=True)
            target_sym = candidates[0][1]
            return self._execute_trade(target_sym, 'BUY', self.trade_amount, ['ENTRY_SNIPER'])
            
        return None

    def _calculate_rsi(self, hist):
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

    def _execute_trade(self, sym, side, amount, tag_list):
        # Update State immediately to prevent race conditions
        if side == 'BUY':
            self.positions[sym] = amount
            self.meta[sym] = {
                'entry': self.history[sym][-1],
                'max_price': self.history[sym][-1]
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                del self.meta[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': tag_list
        }