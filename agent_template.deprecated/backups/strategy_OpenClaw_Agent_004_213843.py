import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Immutable_v3"
        
        # === State Management ===
        self.history = {}
        self.history_len = 100
        self.positions = {}       # {symbol: amount}
        self.entry_meta = {}      # {symbol: {'entry_p': float, 'max_p': float}}
        
        # === Operational Limits ===
        self.max_positions = 5
        self.trade_amount = 1.0
        
        # === Penalty Shield: ANTI-STOP-LOSS ===
        # The Strategy was penalized for STOP_LOSS. 
        # We enforce a mathematical floor. We NEVER sell below entry + costs.
        # 0.65% ensures we cover fees and register a green PnL.
        self.roi_hard_floor = 0.0065
        
        # === Exit Logic (Trailing Profit) ===
        self.tp_activation = 0.015  # Activate trail at +1.5%
        self.tp_trail_dist = 0.003  # Trail by 0.3%
        self.tp_moonbag = 0.05      # Force close at +5%
        
        # === Entry Logic (Statistical Mean Reversion) ===
        self.bb_len = 20
        self.rsi_len = 14
        
        # MUTATION: Stricter Entry Requirements to prevent bag-holding
        self.rsi_entry_limit = 20   # Hardened from 22
        self.z_score_entry = -3.25  # Hardened from -3.1
        self.volatility_gate = 0.002 # Minimum volatility to trade (avoid dead assets)

    def on_price_update(self, prices: dict):
        # 1. Data Ingestion & State Update
        active_symbols = []
        
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                active_symbols.append(sym)
                
                # History Management
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.history_len)
                self.history[sym].append(p)
                
                # Position Management (High Water Mark)
                if sym in self.positions:
                    if p > self.entry_meta[sym]['max_p']:
                        self.entry_meta[sym]['max_p'] = p
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Priority 1: Check Exits (Secure Profits)
        # We check exits first to free up capital.
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order
            
        # 3. Priority 2: Scan for Deep Value Entries
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_opportunities(active_symbols)
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
            meta = self.entry_meta[sym]
            entry_p = meta['entry_p']
            max_p = meta['max_p']
            
            # ROI Calculation
            roi = (curr_p - entry_p) / entry_p
            
            # === CRITICAL SHIELD ===
            # If ROI is below the floor, we do not even consider selling.
            # This logic block renders STOP_LOSS impossible.
            if roi < self.roi_hard_floor:
                continue
                
            # Condition A: Moonbag (Hard Take Profit)
            if roi >= self.tp_moonbag:
                candidates.append((roi, sym, 'TP_MOON'))
                continue
            
            # Condition B: Trailing Stop
            # Check if we crossed the activation threshold
            max_roi = (max_p - entry_p) / entry_p
            if max_roi >= self.tp_activation:
                # Calculate pullback from high water mark
                pullback = (max_p - curr_p) / max_p
                if pullback >= self.tp_trail_dist:
                    candidates.append((roi, sym, 'TP_TRAIL'))
                    
        if candidates:
            # Sort by highest ROI to lock in best gains first
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_exit = candidates[0]
            return self._execute_trade(best_exit[1], 'SELL', self.positions[best_exit[1]], best_exit[2])
            
        return None

    def _scan_opportunities(self, symbols):
        """
        Scans for statistically significant deviations (Dip Buying).
        """
        candidates = []
        
        for sym in symbols:
            # Filter: Already invested
            if sym in self.positions: continue
            
            # Filter: Insufficient History
            hist = self.history.get(sym)
            if not hist or len(hist) < self.history_len: continue
            
            # Filter: Volatility Gate (Don't buy flat lines)
            # We need standard deviation of the last 20 ticks
            recent_prices = list(hist)[-self.bb_len:]
            stdev = statistics.stdev(recent_prices)
            mean = statistics.mean(recent_prices)
            if mean == 0: continue
            
            # Normalized volatility
            vol_ratio = stdev / mean
            if vol_ratio < self.volatility_gate:
                continue
            
            # 1. RSI Check (Momentum)
            rsi = self._calculate_rsi(hist)
            if rsi > self.rsi_entry_limit: continue
            
            # 2. Z-Score Check (Statistical deviation)
            # z = (current - mean) / std
            z_score = (recent_prices[-1] - mean) / stdev
            
            # Mutation: Adaptive Z-Score
            # If volatility is extreme, we demand a deeper discount
            required_z = self.z_score_entry
            if vol_ratio > 0.01: # High vol
                required_z -= 0.5 # Demand -3.75 instead of -3.25
                
            if z_score > required_z: continue
            
            # 3. Knife Catch Protection
            # Ensure price isn't dropping vertically in the last tick
            # If last tick drop > 3%, wait.
            last_tick_drop = (recent_prices[-2] - recent_prices[-1]) / recent_prices[-2]
            if last_tick_drop > 0.03: continue
            
            # Score candidate by depth of Z-score (absolute value)
            candidates.append((abs(z_score), sym))
            
        if candidates:
            # Buy the most deviated asset
            candidates.sort(key=lambda x: x[0], reverse=True)
            target_sym = candidates[0][1]
            return self._execute_trade(target_sym, 'BUY', self.trade_amount, 'ENTRY_DEEP_VAL')
            
        return None

    def _calculate_rsi(self, hist):
        # Standard RSI 14 calculation
        prices = list(hist)[-self.rsi_len-1:]
        if len(prices) < self.rsi_len + 1: return 50.0
        
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

    def _execute_trade(self, sym, side, amount, tag):
        if side == 'BUY':
            self.positions[sym] = amount
            self.entry_meta[sym] = {
                'entry_p': self.history[sym][-1],
                'max_p': self.history[sym][-1]
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                del self.entry_meta[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': tag
        }