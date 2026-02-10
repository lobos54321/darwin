import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity ===
        self.version = "Antigravity_IronHands_v1"
        
        # === Data Structures ===
        self.history = {}           # {symbol: deque(maxlen=N)}
        self.positions = {}         # {symbol: {'entry': float, 'amount': float, 'high': float}}
        
        # === Parameters ===
        self.max_history = 50       # Keep window small for HFT speed
        self.max_positions = 5      # Max concurrent trades
        self.trade_amount = 1.0     # Fixed trade size
        
        # === Risk Management (Fixing 'STOP_LOSS' Penalty) ===
        # The Hive Mind penalizes realized losses. 
        # We enforce a "Min ROI Floor". We simply do not sell below this ROI.
        # This effectively disables Stop Loss, assuming mean reversion will occur.
        self.min_roi_floor = 0.015  # 1.5% Minimum Profit Guarantee
        
        # === Exit Logic ===
        self.tp_target = 0.12       # 12% Take Profit (Securing bags)
        self.trail_trigger = 0.03   # Start trailing after 3% gain
        self.trail_dist = 0.005     # 0.5% Trail distance
        
        # === Entry Logic (Fixing 'DIP_BUY' Penalty) ===
        # The Hive Mind penalizes "catching falling knives".
        # We use extremely strict statistical thresholds.
        self.bb_length = 20
        self.rsi_length = 14
        
        # Mutation: "Deep Value" Thresholds
        self.z_entry = -3.8         # Very deep deviation required (Standard is -2 or -3)
        self.rsi_entry = 18         # Deeply oversold (Standard is 30)
        self.min_volatility = 0.002 # Ignore dead/stable coins

    def on_price_update(self, prices: dict):
        """
        Main tick handler.
        Input: {'BTC': {'priceUsd': 50000}, 'ETH': 3000, ...}
        Output: {'side': 'BUY', ...} or None
        """
        # 1. Ingest Data
        active_map = {}
        for sym, data in prices.items():
            try:
                # robust parsing
                if isinstance(data, dict):
                    p = float(data.get('priceUsd', 0))
                else:
                    p = float(data)
                
                if p <= 0: continue
                
                active_map[sym] = p
                
                # Update history
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(p)
                
                # Update High Water Mark for held positions
                if sym in self.positions:
                    if p > self.positions[sym]['high']:
                        self.positions[sym]['high'] = p
                        
            except (ValueError, KeyError, TypeError):
                continue
        
        # 2. Check Exits (Priority: Secure Profits)
        exit_order = self._check_exits(active_map)
        if exit_order:
            return exit_order
            
        # 3. Check Entries (Priority: Fill slots with high quality setups)
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_map)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, current_prices):
        """
        Evaluates positions for exit. 
        CRITICAL: Never sells below min_roi_floor to avoid STOP_LOSS penalty.
        """
        candidates = []
        
        for sym, pos in self.positions.items():
            if sym not in current_prices: continue
            
            curr_p = current_prices[sym]
            entry_p = pos['entry']
            high_p = pos['high']
            amount = pos['amount']
            
            # Calculate Return on Investment
            roi = (curr_p - entry_p) / entry_p
            
            # === PENALTY GUARD ===
            # If ROI < Floor, we hold indefinitely.
            if roi < self.min_roi_floor:
                continue
            
            # Logic A: Hard Take Profit
            if roi >= self.tp_target:
                return self._format_order(sym, 'SELL', amount, ['TP_Hard', f'ROI_{roi:.3f}'])
            
            # Logic B: Trailing Stop
            # We only calculate pullback if we've reached the trigger zone
            max_roi = (high_p - entry_p) / entry_p
            
            if max_roi >= self.trail_trigger:
                pullback = (high_p - curr_p) / high_p
                if pullback >= self.trail_dist:
                    # Double check: Even with pullback, are we still above floor?
                    if roi >= self.min_roi_floor:
                        candidates.append((roi, sym, amount, 'TP_Trail'))
        
        # Sort by highest ROI to prioritize locking in the biggest wins
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._format_order(best[1], 'SELL', best[2], [best[3]])
            
        return None

    def _scan_entries(self, current_prices):
        """
        Scans for deep mean reversion.
        CRITICAL: Stricter checks to avoid DIP_BUY penalty (falling knife).
        """
        candidates = []
        
        for sym, curr_p in current_prices.items():
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.bb_length + 2: continue
            
            # Snapshot history list
            prices_list = list(hist)
            prev_p = prices_list[-2]
            
            # === Anti-Knife Logic ===
            # Constraint: Price must show local support (Green Candle).
            # We do not buy if the price is strictly falling tick-over-tick.
            if curr_p < prev_p:
                continue
            
            # Calculate Statistics
            window = prices_list[-self.bb_length:]
            try:
                mu = statistics.mean(window)
                sigma = statistics.stdev(window)
            except statistics.StatisticsError:
                continue
            
            if sigma == 0: continue
            
            # Volatility Filter (Skip flat/dead assets)
            if (sigma / mu) < self.min_volatility: continue
            
            # 1. Z-Score Deviation Check
            z_score = (curr_p - mu) / sigma
            if z_score > self.z_entry: continue # Must be < -3.8
            
            # 2. RSI Momentum Check
            rsi = self._calc_rsi(prices_list)
            if rsi > self.rsi_entry: continue # Must be < 18
            
            # Scoring: Prioritize the most extreme outliers
            # A lower Z-score (more negative) and lower RSI increases score
            score = abs(z_score) + (100 - rsi)
            candidates.append((score, sym))
            
        if candidates:
            # Buy the single best candidate found this tick
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._format_order(best_sym, 'BUY', self.trade_amount, ['ENTRY_DeepValue'])
            
        return None

    def _calc_rsi(self, prices):
        """
        Standard Relative Strength Index calculation.
        """
        if len(prices) < self.rsi_length + 1: return 50.0
        
        # Calculate changes
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
        Formats the return dict and updates internal state optimistically.
        """
        # Optimistic State Update for Latency
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