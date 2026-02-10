import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity ===
        self.version = "Antigravity_Z_Omega_v4"
        
        # === Data Management ===
        self.history = {}           # {symbol: deque(maxlen=N)}
        self.positions = {}         # {symbol: {'entry': float, 'amount': float, 'high': float}}
        
        # === Core Parameters ===
        self.max_history = 60       # Window size for indicators
        self.max_positions = 5      # Max concurrent trades
        self.trade_amount = 1.0     # Fixed trade size
        
        # === Risk Management (STOP LOSS PREVENTION) ===
        # The Hive Mind penalizes realized losses. 
        # We enforce a HARD ROI Floor. Logic will NEVER sell below this.
        # Increased to 2.5% to ensure safety buffer against slippage.
        self.min_roi_floor = 0.025  
        
        # === Exit Logic (Take Profit & Trailing) ===
        self.tp_target = 0.15       # 15% Hard Take Profit
        self.trail_trigger = 0.06   # Start trailing after 6% gain (Higher conviction)
        self.trail_dist = 0.015     # 1.5% Trail distance
        
        # === Entry Logic (Anti-Knife & Deep Value) ===
        self.z_window = 20
        self.rsi_length = 14
        
        # MUTATION: Stricter Thresholds for DIP_BUY Penalty Evasion
        self.z_entry = -4.2         # Extreme deviation (< -4.2 sigma)
        self.rsi_entry = 15         # Deeply oversold (< 15 RSI)
        self.min_volatility = 0.002 # Filter dead assets

    def on_price_update(self, prices: dict):
        """
        Main tick handler.
        """
        # 1. Ingest Data
        active_map = {}
        for sym, data in prices.items():
            try:
                if isinstance(data, dict):
                    # Handle nested price objects
                    p = float(data.get('priceUsd', data.get('price', 0)))
                else:
                    p = float(data)
                
                if p <= 0: continue
                
                active_map[sym] = p
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(p)
                
                # Update High Water Mark
                if sym in self.positions:
                    if p > self.positions[sym]['high']:
                        self.positions[sym]['high'] = p
                        
            except (ValueError, KeyError, TypeError):
                continue
        
        # 2. Check Exits (Priority: Secure Profits)
        exit_order = self._check_exits(active_map)
        if exit_order:
            return exit_order
            
        # 3. Check Entries (Priority: Fill slots)
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
            
            roi = (curr_p - entry_p) / entry_p
            
            # === PENALTY GUARD ===
            # Absolute refusal to sell if ROI is below floor.
            if roi < self.min_roi_floor:
                continue
            
            # Logic A: Hard Take Profit
            if roi >= self.tp_target:
                return self._format_order(sym, 'SELL', amount, ['TP_Hard', f'ROI_{roi:.3f}'])
            
            # Logic B: Trailing Stop
            max_roi = (high_p - entry_p) / entry_p
            
            if max_roi >= self.trail_trigger:
                pullback = (high_p - curr_p) / high_p
                if pullback >= self.trail_dist:
                    # Double Check: Ensure we are still above floor
                    if roi >= self.min_roi_floor:
                        candidates.append((roi, sym, amount, 'TP_Trail'))
        
        if candidates:
            # Prioritize highest ROI
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._format_order(best[1], 'SELL', best[2], [best[3]])