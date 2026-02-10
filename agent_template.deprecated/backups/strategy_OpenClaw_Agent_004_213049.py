import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Titanium_v5"
        
        # === State Management ===
        self.history = {}
        self.history_len = 120    # Keep reasonable history for trend/volatility
        self.positions = {}       # Track active positions
        self.entry_meta = {}      # Track entry details: {sym: {'entry_p': float, 'max_p': float, 'tick': int}}
        self.tick_count = 0
        
        # === Operational Constraints ===
        self.max_positions = 5
        self.trade_amount = 1.0
        
        # === Strategy Parameters ===
        # ANTI-PENALTY SHIELD: strictly positive ROI floor.
        # We absorb time-risk (holding) rather than price-risk (realizing loss).
        # 0.8% floor covers typical exchange fees + slippage + net profit.
        self.roi_floor = 0.008 
        
        # Exits
        self.tp_target = 0.03       # 3.0% Primary Take Profit
        self.trail_arm_roi = 0.015  # Arm trailing stop after 1.5% gains
        self.trail_offset = 0.004   # 0.4% trailing distance
        
        # Entries (Stricter Filters)
        self.bb_len = 35
        self.rsi_len = 14
        self.z_thresh_neutral = -3.5
        self.z_thresh_bear = -4.2   # Stricter requirement for downtrends
        self.rsi_thresh = 21

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Data Ingestion & State Updates
        active_symbols = []
        for sym, data in prices.items():
            active_symbols.append(sym)
            try:
                current_price = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_len)
            self.history[sym].append(current_price)
            
            # Update High-Water Mark for active positions
            if sym in self.entry_meta:
                if current_price > self.entry_meta[sym]['max_p']:
                    self.entry_meta[sym]['max_p'] = current_price

        # 2. Exit Logic (Priority: Secure Profits)
        # We check exits first to free up slots and lock in gains.
        exit_signal = self._scan_exits(prices)
        if exit_signal:
            return exit_signal
            
        # 3. Entry Logic (Priority: High Quality Sniping)
        # Only scan if we have capacity
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(active_symbols)
            if entry_signal:
                return entry_signal
                
        return None

    def _scan_exits(self, prices):
        """
        Evaluates active positions for exit conditions.
        CRITICAL: Never generates a SELL signal if ROI < roi_floor.
        """
        candidates = []
        
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_p = float(prices[sym]['priceUsd'])
            meta = self.entry_meta[sym]
            entry_p = meta['entry_p']
            max_p = meta['max_p']
            
            roi = (curr_p - entry_p) / entry_p
            
            # === PENALTY AVOIDANCE ===
            # Constraint: No Stop Loss. 
            # If current ROI is below the floor, we hold indefinitely.
            if roi < self.roi_floor:
                continue
                
            # Logic A: Hard Take Profit
            if roi >= self.tp_target:
                candidates.append((roi, sym, 'TP_HARD'))
                continue
                
            # Logic B: Trailing Stop
            # If price reached significant profit, protect it.
            max_roi = (max_p - entry_p) / entry_p
            if max_roi >= self.trail_arm_roi:
                # Calculate drawdown from peak
                drawdown = (max_p - curr_p) / max_p
                if drawdown >= self.trail_offset:
                    candidates.append((roi, sym, 'TP_TRAIL'))
                    continue
            
            # Logic C: Stale Position Clearance
            # If held for a long time (>200 ticks) and profitable (above floor),
            # sell to free up capital for potentially faster moving assets.
            ticks_held = self.tick_count - meta['tick']
            if ticks_held > 200 and roi > 0.01:
                candidates.append((roi, sym, 'TP_STALE'))

        if candidates:
            # Sort by ROI (highest first) to prioritize banking the biggest wins
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_exit = candidates[0]
            return self._execute_trade(best_exit[1], 'SELL', self.positions[best_exit[1]], best_exit[2])
            
        return None

    def _scan_entries(self, symbols):
        """
        Scans for deep value anomalies (Dip Buying).
        Applies stricter filtering to minimize bag-holding risk.
        """
        candidates = []
        
        for sym in symbols:
            # Filter: Already in position
            if sym in self.positions: continue
            
            # Filter: Insufficient Data
            hist = self.history.get(sym)
            if not hist or len(hist) < self.bb_len: continue
            
            price_list = list(hist)
            curr_p = price_list[-1]
            
            # 1. RSI Check (Fast filter)
            rsi = self._calc_rsi(price_list, self.rsi_len)
            if rsi > self.rsi_thresh:
                continue
            
            # 2. Bollinger Stats & Z-Score
            window = price_list[-self.bb_len:]
            mean = statistics.mean(window)
            stdev = statistics.stdev(window)
            
            if stdev == 0: continue
            z_score = (curr_p - mean) / stdev
            
            # 3. Mutation: Trend-Adaptive Thresholds
            # If we are below the long-term mean, we are in a bear trend.
            # In a bear trend, dips keep dipping. We require a much deeper Z-score.
            long_window = price_list[-min(len(price_list), 80):]
            long_mean = statistics.mean(long_window)
            
            req_z = self.z_thresh_neutral
            if curr_p < long_mean:
                req_z = self.z_thresh_bear # e.g. -4.2
                
            if z_score > req_z:
                continue
                
            # 4. Mutation: Velocity Brake
            # Prevent catching a "Falling Knife" that is accelerating.
            # Check price change of the last tick vs local volatility.
            if len(price_list) > 5:
                delta = curr_p - price_list[-2]
                if delta < 0:
                    # Calculate mean absolute deviation of last 5 ticks
                    recent_vol = statistics.mean([abs(price_list[i] - price_list[i-1]) for i in range(-5, -1)])
                    # If this single drop is massive compared to recent noise, wait for stabilization
                    if recent_vol > 0 and abs(delta) > 4.5 * recent_vol:
                        continue

            candidates.append((abs(z_score), sym))
            
        if candidates:
            # Prioritize the most extreme deviation
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._execute_trade(best_sym, 'BUY', self.trade_amount, 'ENTRY_DEEP_VAL')
            
        return None

    def _execute_trade(self, sym, side, amount, tag):
        if side == 'BUY':
            self.positions[sym] = amount
            self.entry_meta[sym] = {
                'entry_p': self.history[sym][-1],
                'max_p': self.history[sym][-1],
                'tick': self.tick_count
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

    def _calc_rsi(self, prices, period):
        # Standard RSI calculation adapted for list input
        if len(prices) < period + 1:
            return 50.0
            
        # Optimize: Calculate only necessary deltas
        # We need the last 'period' changes
        changes = []
        for i in range(1, period + 1):
            changes.append(prices[-i] - prices[-i-1])
            
        gains = sum(x for x in changes if x > 0)
        losses = sum(abs(x) for x in changes if x < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))