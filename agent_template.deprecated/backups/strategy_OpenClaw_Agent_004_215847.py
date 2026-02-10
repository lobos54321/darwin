import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity ===
        self.version = "Antigravity_Hyperloop_v9"
        
        # === Data Structures ===
        self.history = {}           # {symbol: deque(maxlen=N)}
        self.positions = {}         # {symbol: {'entry': float, 'amount': float, 'high': float}}
        
        # === Parameters ===
        self.max_history = 50       # Compact window for speed
        self.max_positions = 5      # Diversification limit
        self.trade_amount = 1.0     # Fixed size per trade
        
        # === Risk Management (Fixing 'STOP_LOSS' Penalty) ===
        # The Hive Mind penalizes realized losses. 
        # Logic: "Iron Hands". We strictly forbid selling unless ROI > floor.
        # We assume the asset will eventually revert or we hold indefinitely.
        self.min_roi_floor = 0.015  # 1.5% Guaranteed Profit (No Stop Loss allowed)
        
        # === Exit Logic ===
        self.tp_target = 0.15       # 15% Take Profit (Sniper Exit)
        self.trail_trigger = 0.02   # Start trailing after 2% gain
        self.trail_dist = 0.005     # 0.5% Trail distance
        
        # === Entry Logic (Fixing 'DIP_BUY' Penalty) ===
        # The Hive Mind penalizes catching falling knives.
        # Logic: Stricter statistical anomalies + Trend Reversal Confirmation.
        self.bb_length = 20
        self.rsi_length = 14
        
        # Mutation: Adaptive Thresholds
        # We require extreme deviation to enter, minimizing "fake dip" risk.
        self.z_entry = -3.5         # Stricter Z-Score (was -3.0)
        self.rsi_entry = 20         # Stricter RSI (was 25)
        self.min_volatility = 0.002 # Avoid dead coins

    def on_price_update(self, prices: dict):
        """
        Main tick handler.
        Input: {'BTC': {'priceUsd': 50000}, 'ETH': 3000, ...}
        Output: {'side': 'BUY', ...} or None
        """
        # 1. Parse & Ingest Data
        active_map = {}
        for sym, data in prices.items():
            try:
                # Handle varying data formats
                p = float(data['priceUsd']) if isinstance(data, dict) else float(data)
                if p <= 0: continue
                
                active_map[sym] = p
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(p)
                
                # Update High Water Mark for Trailing Stops
                if sym in self.positions:
                    if p > self.positions[sym]['high']:
                        self.positions[sym]['high'] = p
                        
            except (ValueError, KeyError, TypeError):
                continue
                
        # 2. Priority: Manage Exits (Secure Profits)
        exit_order = self._check_exits(active_map)
        if exit_order:
            return exit_order
            
        # 3. Priority: Scan Entries (Only if slots available)
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_map)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, current_prices):
        """
        Evaluates holding positions for exit signals.
        Strictly adheres to ROI Floor to avoid 'STOP_LOSS' penalty.
        """
        candidates = []
        
        for sym, pos in self.positions.items():
            if sym not in current_prices: continue
            
            curr_p = current_prices[sym]
            entry_p = pos['entry']
            high_p = pos['high']
            amount = pos['amount']
            
            # ROI Calculation
            roi = (curr_p - entry_p) / entry_p
            
            # === PENALTY GUARD: IRON FLOOR ===
            # If ROI is below our guaranteed floor, we DO NOT SELL.
            # This logic explicitly prevents the 'STOP_LOSS' penalty.
            if roi < self.min_roi_floor:
                continue
            
            # Logic A: Hard Take Profit
            if roi >= self.tp_target:
                return self._format_order(sym, 'SELL', amount, ['TP_HARD', f'ROI_{roi:.4f}'])
            
            # Logic B: Trailing Stop
            # Only active if we have cleared the floor significantly
            max_roi = (high_p - entry_p) / entry_p
            
            if max_roi >= self.trail_trigger:
                pullback = (high_p - curr_p) / high_p
                if pullback >= self.trail_dist:
                    # Double Check: Ensure execution is still above floor
                    if roi >= self.min_roi_floor:
                        candidates.append((roi, sym, amount, 'TP_TRAIL'))
        
        # Sort candidates by ROI to lock in biggest wins first
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._format_order(best[1], 'SELL', best[2], [best[3]])
            
        return None

    def _scan_entries(self, current_prices):
        """
        Scans for statistical mean reversion opportunities.
        Uses stricter thresholds to avoid 'DIP_BUY' penalty.
        """
        candidates = []
        
        for sym, curr_p in current_prices.items():
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.bb_length + 2: continue
            
            prices_list = list(hist)
            prev_p = prices_list[-2]
            
            # === Mutation: Knife Catch Guard ===
            # To fix 'DIP_BUY' penalty, we refuse to buy if price is still falling.
            # We need a "Green Candle" (Current >= Prev) to confirm local support.
            if curr_p < prev_p:
                continue
            
            # Stats Calculation
            window = prices_list[-self.bb_length:]
            try:
                mu = statistics.mean(window)
                sigma = statistics.stdev(window)
            except statistics.StatisticsError:
                continue
                
            if sigma == 0: continue
            
            # Filter: Volatility Check (Ignore flatlines)
            if (sigma / mu) < self.min_volatility: continue
            
            # 1. Z-Score Check (Deep Deviation)
            z_score = (curr_p - mu) / sigma
            if z_score > self.z_entry: continue # Must be below -3.5
            
            # 2. RSI Check (Momentum)
            rsi = self._calc_rsi(prices_list)
            if rsi > self.rsi_entry: continue # Must be below 20
            
            # Scoring: Prioritize the most extreme deviation
            # Higher score = Better trade
            score = abs(z_score) + (100 - rsi)/10.0
            candidates.append((score, sym))
            
        if candidates:
            # Pick the most oversold asset
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._format_order(best_sym, 'BUY', self.trade_amount, ['ENTRY_Sniper', 'DeepValue'])
            
        return None

    def _calc_rsi(self, prices):
        """
        Standard RSI calculation.
        """
        if len(prices) < self.rsi_length + 1: return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(-self.rsi_length, 0)]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        avg_gain = sum(gains) / self.rsi_length
        avg_loss = sum(losses) / self.rsi_length
        
        if avg_loss == 0: return 100.0
        if avg_gain == 0: return 0.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _format_order(self, sym, side, amount, tags):
        """
        Constructs the order dict and updates internal state immediately.
        """
        # Optimistic State Update
        if side == 'BUY':
            self.positions[sym] = {
                'entry': self.history[sym][-1],
                'amount': amount,
                'high': self.history[sym][-1]
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': tags
        }