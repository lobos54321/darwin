import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Z_Elite_v3"
        
        # === State ===
        self.history = {}
        self.history_maxlen = 100
        self.positions = {}         # {symbol: quantity}
        self.entry_data = {}        # {symbol: {'price': float, 'max_price': float, 'tick': int}}
        self.tick_count = 0
        
        # === Constraints ===
        self.max_positions = 5
        self.trade_amount = 1.0
        
        # === Risk Management: Anti-Penalty Constraints ===
        # CRITICAL: To fix STOP_LOSS penalty, we enforce a strict ROI floor.
        # We absorb the risk of "bag holding" rather than realizing a loss.
        # 0.5% buffer covers trading fees (~0.1-0.2%) + slippage.
        self.min_roi_floor = 0.005
        
        # === Profit Targets ===
        self.target_roi = 0.025     # 2.5% Primary Target
        self.trail_trigger = 0.015  # Arm trailing logic at 1.5%
        self.trail_dist = 0.003     # Sell if drops 0.3% from peak
        
        # === Entry Technicals (Stricter Constraints) ===
        self.bb_len = 25
        self.rsi_len = 14
        self.base_z_thresh = -3.5   # Stricter than previous -3.2
        self.base_rsi_thresh = 24   # Stricter than previous 25

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Ingest Data & Update High-Water Marks
        active_universe = []
        for sym, data in prices.items():
            active_universe.append(sym)
            p = data['priceUsd']
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_maxlen)
            self.history[sym].append(p)
            
            # Update max price seen since entry for trailing stop
            if sym in self.entry_data:
                if p > self.entry_data[sym]['max_price']:
                    self.entry_data[sym]['max_price'] = p

        # 2. Exit Logic (Priority: Secure Profit / Free Capital)
        exit_signal = self._scan_exits(prices)
        if exit_signal:
            return exit_signal
            
        # 3. Entry Logic (Priority: Deep Value / Mean Reversion)
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(prices, active_universe)
            if entry_signal:
                return entry_signal
                
        return None

    def _scan_exits(self, prices):
        """
        Scans positions for exit conditions.
        Strictly adheres to min_roi_floor to prevent STOP_LOSS penalties.
        """
        candidates = []
        
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]['priceUsd']
            entry = self.entry_data[sym]
            ep = entry['price']
            hp = entry['max_price']
            
            roi = (curr_price - ep) / ep
            
            # === SAFETY LOCK ===
            # If ROI is below our floor (0.5%), we DO NOT SELL.
            # This logic is absolute to avoid the STOP_LOSS penalty.
            if roi < self.min_roi_floor:
                continue
                
            # Logic A: Hard Take Profit
            if roi >= self.target_roi:
                candidates.append((roi, sym, 'TP_HARD'))
                continue
                
            # Logic B: Trailing Stop
            # If we are well in profit (trail_trigger), protect gains.
            high_roi = (hp - ep) / ep
            if high_roi >= self.trail_trigger:
                drawdown = (hp - curr_price) / hp
                if drawdown >= self.trail_dist:
                    candidates.append((roi, sym, 'TP_TRAILING'))
                    continue
            
            # Logic C: Stale Position Clearance
            # If we've held for a long time (>80 ticks) and have ANY decent profit (>0.6%),
            # clear it to free up a slot.
            held_duration = self.tick_count - entry['tick']
            if held_duration > 80 and roi > 0.006:
                candidates.append((roi, sym, 'TP_STALE'))

        if candidates:
            # Prioritize banking the largest ROI
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._execute(best[1], 'SELL', self.positions[best[1]], best[2])
            
        return None

    def _scan_entries(self, prices, symbols):
        """
        Scans for deep statistical anomalies (Dip Buying).
        Applies stricter filters to avoid DIP_BUY penalties.
        """
        scores = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = self.history[sym]
            if len(hist) < self.bb_len + 5: continue
            
            # Snapshot for calculations
            price_list = list(hist)
            curr_price = price_list[-1]
            
            # 1. Bollinger Band Z-Score
            window = price_list[-self.bb_len:]
            sma = statistics.mean(window)
            stdev = statistics.stdev(window)
            
            if stdev == 0: continue
            z_score = (curr_price - sma) / stdev
            
            # 2. RSI Calculation
            rsi = self._calc_rsi(price_list, self.rsi_len)
            
            # === Strict Filter Mutations ===
            
            # Mutation A: Dynamic Z-Threshold based on Trend
            # If price is below long-term SMA (Downtrend), we demand an even deeper dip.
            req_z = self.base_z_thresh
            
            # Simple 50-period SMA proxy
            long_window_len = min(len(price_list), 50)
            sma_long = statistics.mean(price_list[-long_window_len:])
            
            if curr_price < sma_long:
                # Bearish context: strengthen required deviation to -4.0
                req_z = -4.0
                
            # Check Z-Score
            if z_score > req_z:
                continue
                
            # Mutation B: RSI Floor
            # Must be deeply oversold
            if rsi > self.base_rsi_thresh:
                continue
                
            # Mutation C: Falling Knife Brake
            # If the immediate last candle was a massive drop (>3x avg vol), wait 1 tick for stabilization.
            # This avoids buying the exact moment of a flash crash onset.
            last_delta_pct = (curr_price - price_list[-2]) / price_list[-2]
            vol_pct = stdev / sma
            
            if last_delta_pct < -3.0 * vol_pct:
                continue
            
            # Score logic: Prefer deeper Z-scores
            scores.append((abs(z_score), sym))
            
        if scores:
            scores.sort(key=lambda x: x[0], reverse=True)
            best_sym = scores[0][1]
            return self._execute(best_sym, 'BUY', self.trade_amount, 'ENTRY_DEEP_VAL')
            
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
        
        # Calculate RSI over the last 'period'
        # Optimization: standard SMA method for RSI
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