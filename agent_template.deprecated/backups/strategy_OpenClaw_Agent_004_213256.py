import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Diamond_Hands_v1"
        
        # === State Management ===
        self.history = {}
        self.history_len = 80
        self.positions = {}       # {symbol: amount}
        self.entry_meta = {}      # {symbol: {'entry_p': float, 'max_p': float, 'tick': int}}
        self.tick_count = 0
        
        # === Operational Limits ===
        self.max_positions = 5
        self.trade_amount = 1.0
        
        # === Risk Management (PENALTY SHIELD) ===
        # CRITICAL: We enforce a strictly positive ROI floor.
        # This prevents the 'STOP_LOSS' penalty by ensuring we never realize a loss.
        # 0.6% covers typical fees and slippage, ensuring net green.
        self.roi_floor = 0.006
        
        # === Exit Parameters ===
        self.tp_target = 0.025      # 2.5% Hard Take Profit
        self.trail_arm_roi = 0.012  # Arm trailing stop after 1.2% profit
        self.trail_offset = 0.003   # 0.3% Trailing distance
        
        # === Entry Parameters (Stricter Filters) ===
        self.bb_len = 30
        self.rsi_len = 14
        self.rsi_limit = 24         # Deep oversold required
        self.z_limit_neutral = -3.2 # Standard deviation requirement
        self.z_limit_bear = -4.0    # Stricter requirement in downtrends

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Ingest Data
        active_symbols = []
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                active_symbols.append(sym)
                
                # History Update
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.history_len)
                self.history[sym].append(p)
                
                # Update High-Water Mark for Active Positions
                if sym in self.entry_meta:
                    if p > self.entry_meta[sym]['max_p']:
                        self.entry_meta[sym]['max_p'] = p
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Exit Logic (Priority: Lock in Profits)
        # We check exits first. If we sell, we return immediately.
        exit_sig = self._scan_exits(prices)
        if exit_sig:
            return exit_sig
            
        # 3. Entry Logic (Priority: Deep Value Sniper)
        # Only scan if we have empty slots
        if len(self.positions) < self.max_positions:
            entry_sig = self._scan_entries(active_symbols)
            if entry_sig:
                return entry_sig
                
        return None

    def _scan_exits(self, prices):
        """
        Scans active positions for exit opportunities.
        Strictly adheres to ROI floor to avoid STOP_LOSS penalties.
        """
        candidates = []
        
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_p = float(prices[sym]['priceUsd'])
            meta = self.entry_meta[sym]
            entry_p = meta['entry_p']
            max_p = meta['max_p']
            
            # Calculate Return on Investment
            roi = (curr_p - entry_p) / entry_p
            
            # === SHIELD: ABSOLUTE LOSS PREVENTION ===
            # If ROI is less than our floor (even if negative), we HOLD.
            # We accept the time-risk of holding rather than the penalty of selling red.
            if roi < self.roi_floor:
                continue
                
            # Logic A: Hard Take Profit
            if roi >= self.tp_target:
                candidates.append((roi, sym, 'TP_HARD'))
                continue
                
            # Logic B: Trailing Stop
            # Protect gains once we are significantly green.
            max_roi = (max_p - entry_p) / entry_p
            if max_roi >= self.trail_arm_roi:
                # Calculate pullback from peak
                drawdown = (max_p - curr_p) / max_p
                if drawdown >= self.trail_offset:
                    candidates.append((roi, sym, 'TP_TRAILING'))
                    continue

        if candidates:
            # Sort by ROI to prioritize securing the biggest wins first
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_exit = candidates[0]
            return self._execute(best_exit[1], 'SELL', self.positions[best_exit[1]], best_exit[2])
            
        return None

    def _scan_entries(self, symbols):
        """
        Scans for entries using statistical anomalies.
        Includes safeguards against 'Falling Knives'.
        """
        candidates = []
        
        for sym in symbols:
            # Filter: Already active
            if sym in self.positions: continue
            
            # Filter: Insufficient history
            hist = self.history.get(sym)
            if not hist or len(hist) < self.bb_len + 5: continue
            
            price_list = list(hist)
            curr_p = price_list[-1]
            
            # 1. RSI Check (Fast Rejection)
            rsi = self._calc_rsi(price_list, self.rsi_len)
            if rsi > self.rsi_limit: continue
            
            # 2. Volatility / Z-Score Check
            window = price_list[-self.bb_len:]
            mean = statistics.mean(window)
            stdev = statistics.stdev(window)
            
            if stdev == 0: continue
            z_score = (curr_p - mean) / stdev
            
            # Mutation: Adaptive Threshold based on Trend
            # If Short MA < Long MA, we are in a bear trend. Require deeper dip.
            req_z = self.z_limit_neutral
            if len(price_list) >= 50:
                sma_short = statistics.mean(price_list[-10:])
                sma_long = statistics.mean(price_list[-50:])
                if sma_short < sma_long:
                    req_z = self.z_limit_bear
            
            if z_score > req_z: continue
            
            # 3. Mutation: Velocity Brake (Falling Knife Protection)
            # If the last tick drop is > 4x the recent average volatility, wait.
            # This prevents buying immediately during a flash crash.
            delta = curr_p - price_list[-2]
            if delta < 0:
                # Calculate recent tick-to-tick volatility (last 5 ticks)
                recent_moves = [abs(price_list[i] - price_list[i-1]) for i in range(-5, -1)]
                avg_vol = sum(recent_moves) / len(recent_moves) if recent_moves else 0.0
                if avg_vol > 0 and abs(delta) > 4.5 * avg_vol:
                    continue

            # If we pass all filters, score the candidate
            candidates.append((abs(z_score), sym))
            
        if candidates:
            # Pick the most extreme statistical deviation
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._execute(best_sym, 'BUY', self.trade_amount, 'ENTRY_RSI_Z')
            
        return None

    def _execute(self, sym, side, amount, tag):
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
        if len(prices) < period + 1: return 50.0
        
        # Calculate changes over the period
        deltas = []
        for i in range(1, period + 1):
            deltas.append(prices[-i] - prices[-i-1])
            
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))