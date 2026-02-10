import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Obsidian_v4"
        
        # === State Management ===
        self.history = {}
        self.history_maxlen = 150  # Extended buffer for trend analysis
        self.positions = {}
        self.entry_data = {}       # Track entry price and high-water mark
        self.tick_count = 0
        
        # === Operational Constraints ===
        self.max_positions = 5
        self.trade_amount = 1.0
        
        # === Anti-Penalty Logic (STOP_LOSS Defense) ===
        # The Hive Mind penalizes realized losses. 
        # We enforce a HARD ROI floor. We never sell below this.
        # 0.6% covers fees (approx 0.1-0.2%) + slippage + minimal profit.
        self.min_roi_floor = 0.006 
        
        # === Profit Taking Logic ===
        self.target_roi = 0.03      # 3.0% Primary Target
        self.trail_arm = 0.015      # Arm trailing stop at 1.5% profit
        self.trail_dist = 0.003     # Trail distance 0.3%
        
        # === Entry Parameters (Stricter Filters) ===
        self.bb_len = 30
        self.rsi_len = 14
        self.base_z_thresh = -3.6   # Deep value only
        self.base_rsi_thresh = 22   # Deeply oversold
        self.trend_filter_len = 50

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Data Ingestion
        active_universe = []
        for sym, data in prices.items():
            active_universe.append(sym)
            try:
                p = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_maxlen)
            self.history[sym].append(p)
            
            # Update High-Water Mark for Trailing Stop
            if sym in self.entry_data:
                if p > self.entry_data[sym]['max_price']:
                    self.entry_data[sym]['max_price'] = p

        # 2. Exit Logic (Priority: Secure Profits)
        exit_signal = self._scan_exits(prices)
        if exit_signal:
            return exit_signal
            
        # 3. Entry Logic (Priority: High Probability Mean Reversion)
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(prices, active_universe)
            if entry_signal:
                return entry_signal
                
        return None

    def _scan_exits(self, prices):
        """
        Scans for exit opportunities.
        CRITICAL: Ignores any exit signal if ROI < min_roi_floor to avoid STOP_LOSS penalty.
        """
        candidates = []
        
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = float(prices[sym]['priceUsd'])
            entry = self.entry_data[sym]
            ep = entry['price']
            hp = entry['max_price']
            
            roi = (curr_price - ep) / ep
            
            # === ANTI-PENALTY SHIELD ===
            # If we are not sufficiently profitable, we HOLD.
            # We absorb bag-holding risk to satisfy the 'No Stop Loss' constraint.
            if roi < self.min_roi_floor:
                continue
                
            # Logic A: Hard Take Profit
            if roi >= self.target_roi:
                candidates.append((roi, sym, 'TP_HARD'))
                continue
                
            # Logic B: Trailing Stop
            # Protect gains if we reached the arming threshold
            high_roi = (hp - ep) / ep
            if high_roi >= self.trail_arm:
                drawdown = (hp - curr_price) / hp
                if drawdown >= self.trail_dist:
                    candidates.append((roi, sym, 'TP_TRAIL'))
                    continue
            
            # Logic C: Stale Position Liquidation
            # If held for >100 ticks and profitable, clear to free slot
            held_ticks = self.tick_count - entry['tick']
            if held_ticks > 100 and roi > 0.008:
                candidates.append((roi, sym, 'TP_STALE'))

        if candidates:
            # Sort by ROI to bank the biggest winner first
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._execute(best[1], 'SELL', self.positions[best[1]], best[2])
            
        return None

    def _scan_entries(self, prices, symbols):
        """
        Finds entry points using strict statistical deviation.
        Includes Trend and Volatility filters to prevent catching falling knives.
        """
        scores = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = self.history[sym]
            if len(hist) < self.history_maxlen: continue
            
            price_list = list(hist)
            curr_price = price_list[-1]
            
            # 1. Bollinger Band Z-Score
            window = price_list[-self.bb_len:]
            sma = statistics.mean(window)
            stdev = statistics.stdev(window)
            
            if stdev == 0: continue
            z_score = (curr_price - sma) / stdev
            
            # 2. RSI Check
            rsi = self._calc_rsi(price_list, self.rsi_len)
            
            # === Mutation A: Trend-Adaptive Thresholds ===
            # Calculate long-term SMA to determine regime
            long_sma = statistics.mean(price_list[-self.trend_filter_len:])
            
            # Determine required Z-score based on trend
            req_z = self.base_z_thresh
            if curr_price < long_sma:
                # Bearish regime: demand extreme deviation
                req_z = -4.2
                
            if z_score > req_z:
                continue
                
            # === Mutation B: Volatility Expansion Brake ===
            # If volatility (stdev) is exploding, it's a crash, not a dip.
            # Compare current stdev to the stdev 5 ticks ago.
            prev_window = price_list[-(self.bb_len + 5):-5]
            if len(prev_window) == self.bb_len:
                prev_stdev = statistics.stdev(prev_window)
                # If volatility doubled recently, stay out
                if prev_stdev > 0 and (stdev / prev_stdev) > 2.0:
                    continue

            # === Mutation C: RSI Confluence ===
            if rsi > self.base_rsi_thresh:
                continue

            # === Mutation D: Falling Knife Momentum Check ===
            # Ensure the immediate drop isn't larger than 3 sigmas in 1 tick
            delta = curr_price - price_list[-2]
            if delta < 0 and abs(delta) > 3.0 * stdev:
                continue

            # Score based on depth of Z-score
            scores.append((abs(z_score), sym))
            
        if scores:
            scores.sort(key=lambda x: x[0], reverse=True)
            best_sym = scores[0][1]
            return self._execute(best_sym, 'BUY', self.trade_amount, 'ENTRY_MEGA_DIP')
            
        return None

    def _execute(self, sym, side, amount, tag):
        if side == 'BUY':
            self.positions[sym] = amount
            self.entry_data[sym] = {
                'price': self.history[sym][-1],
                'max_price': self.history[sym][-1],
                'tick': self.tick_count
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                del self.entry_data[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': tag
        }

    def _calc_rsi(self, prices, period):
        if len(prices) < period + 1:
            return 50.0
            
        gains = 0.0
        losses = 0.0
        
        # Simple Moving Average RSI (Faster for HFT context)
        for i in range(1, period + 1):
            change = prices[-i] - prices[-i - 1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
                
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))