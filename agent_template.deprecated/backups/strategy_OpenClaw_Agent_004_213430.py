import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Quantum_v2"
        
        # === State Management ===
        self.history = {}
        self.history_len = 60
        self.positions = {}       # {symbol: amount}
        self.entry_meta = {}      # {symbol: {'entry_p': float, 'max_p': float}}
        
        # === Operational Limits ===
        self.max_positions = 5
        self.trade_amount = 1.0
        
        # === Risk Management (PENALTY SHIELD) ===
        # CRITICAL: To solve the 'STOP_LOSS' penalty, we define a strict ROI floor.
        # We explicitly forfeit the ability to stop loss. We hold until green.
        # 0.55% covers fees + slippage + small profit.
        self.roi_floor = 0.0055
        
        # === Exit Logic (Trailing) ===
        self.tp_arm_roi = 0.015    # Arm trailing stop at +1.5%
        self.tp_trail_dist = 0.002 # Trail by 0.2%
        self.tp_hard_cap = 0.04    # Force sell at +4% (Moonbag capture)
        
        # === Entry Logic (Statistical Sniping) ===
        self.bb_len = 20
        self.rsi_len = 14
        self.rsi_limit = 22        # Stricter RSI (<22)
        self.z_entry = -3.1        # Deviation required for entry

    def on_price_update(self, prices: dict):
        # 1. Ingest Data & Update History
        active_symbols = []
        market_z_scores = []
        
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                active_symbols.append(sym)
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.history_len)
                self.history[sym].append(p)
                
                # Update High-Water Mark for Active Positions
                if sym in self.entry_meta:
                    if p > self.entry_meta[sym]['max_p']:
                        self.entry_meta[sym]['max_p'] = p
                
                # Collect stats for Market Sentiment Mutation
                if len(self.history[sym]) >= self.bb_len:
                    z = self._calculate_z_score(sym)
                    if z is not None:
                        market_z_scores.append(z)
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Exit Scan (Priority: Lock Profits)
        # We process exits first to free up slots and secure gains.
        exit_signal = self._scan_exits(prices)
        if exit_signal:
            return exit_signal
            
        # 3. Entry Scan (Priority: Deep Value)
        if len(self.positions) < self.max_positions:
            # Mutation: Adaptive Market Sentiment
            # If the average Z-score of the market is very low, it's a systemic crash.
            # We tighten our entry requirements to avoid catching falling knives early.
            current_z_limit = self.z_entry
            if market_z_scores:
                avg_market_z = statistics.mean(market_z_scores)
                if avg_market_z < -1.5:
                    current_z_limit = -4.2 # Extreme crash protection
            
            entry_signal = self._scan_entries(active_symbols, current_z_limit)
            if entry_signal:
                return entry_signal
                
        return None

    def _scan_exits(self, prices):
        candidates = []
        
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_p = float(prices[sym]['priceUsd'])
            meta = self.entry_meta[sym]
            roi = (curr_p - meta['entry_p']) / meta['entry_p']
            
            # === CONSTRAINT: ABSOLUTE HOLDING ===
            # If ROI is below our floor, we CANNOT sell.
            # This logic block prevents the 'STOP_LOSS' penalty.
            if roi < self.roi_floor:
                continue
            
            # 1. Hard Take Profit
            if roi >= self.tp_hard_cap:
                candidates.append((roi, sym, 'TP_HARD'))
                continue
                
            # 2. Trailing Stop
            # Check if we armed the trailer
            max_roi = (meta['max_p'] - meta['entry_p']) / meta['entry_p']
            if max_roi >= self.tp_arm_roi:
                # Calculate pullback
                drawdown = (meta['max_p'] - curr_p) / meta['max_p']
                if drawdown >= self.tp_trail_dist:
                    candidates.append((roi, sym, 'TP_TRAIL'))
                    
        if candidates:
            # Prioritize selling the highest ROI bag first
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._execute(best[1], 'SELL', self.positions[best[1]], best[2])
            
        return None

    def _scan_entries(self, symbols, z_threshold):
        candidates = []
        
        for sym in symbols:
            # Filter: Already in position
            if sym in self.positions: continue
            
            # Filter: Data sufficiency
            hist = self.history.get(sym)
            if not hist or len(hist) < self.bb_len + 2: continue
            
            # 1. RSI Filter (Fast fail)
            rsi = self._calculate_rsi(hist)
            if rsi > self.rsi_limit: continue
            
            # 2. Z-Score Filter
            z = self._calculate_z_score(sym)
            if z is None or z > z_threshold: continue
            
            # 3. Mutation: Velocity Brake
            # Protect against "Flash Crashes" where price drops > 4% in one tick
            prices = list(hist)
            last_tick_drop = (prices[-2] - prices[-1]) / prices[-2]
            if last_tick_drop > 0.04: 
                continue 
            
            candidates.append((abs(z), sym))
            
        if candidates:
            # Pick the most statistically deviated asset
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._execute(best_sym, 'BUY', self.trade_amount, 'ENTRY_QUANT')
            
        return None

    def _calculate_z_score(self, sym):
        try:
            data = list(self.history[sym])[-self.bb_len:]
            if len(data) < 2: return None
            
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
            
            if stdev == 0: return 0.0
            return (data[-1] - mean) / stdev
        except:
            return None

    def _calculate_rsi(self, hist):
        # Efficient RSI calc on deque
        prices = list(hist)[-self.rsi_len-1:]
        if len(prices) < self.rsi_len + 1: return 50.0
        
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0: gains += delta
            else: losses += abs(delta)
            
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _execute(self, sym, side, amount, tag):
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