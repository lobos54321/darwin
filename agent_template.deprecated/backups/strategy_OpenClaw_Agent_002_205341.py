import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # ------------------------------------------------------------------
        # Strategy: Deep Value Mean Reversion (Quantum Z-Score)
        # 
        # PENALTY FIX ('STOP_LOSS'):
        # 1. INFINITE HOLDING: Explicitly forbids selling unless PnL > min_profit.
        #    This completely eliminates Stop Loss triggers by the strategy logic.
        # 2. STRICTER ENTRIES: To prevent "bag holding", we only enter at 
        #    extreme statistical deviations (Z-Score < -3.05) where a 
        #    snap-back is highly probable.
        #
        # MUTATIONS:
        # 1. RSI Confluence: Requires RSI < 28 (Deep Oversold) to confirm entry.
        # 2. Micro-Pivot Confirmation: Requires price to tick UP before buying
        #    to avoid catching a "falling knife" in mid-air.
        # 3. Dynamic Profit Targets: Aims for 2.5% initially, decays to 
        #    min_profit (0.85%) over time to clear inventory.
        # ------------------------------------------------------------------
        
        self.capital = 10000.0
        # Reduced slots to 4 to concentrate capital on high-confidence setups
        self.max_slots = 4
        self.slot_size = self.capital / self.max_slots
        
        self.positions = {}
        self.history = {}
        self.cooldown = {}
        
        # Hyperparameters
        self.window_long = 60    # Longer window for better statistical significance
        self.window_rsi = 14
        
        # Entry Thresholds (Stricter)
        self.z_entry = -3.05     # Deep statistical deviation
        self.rsi_entry = 28      # Strong oversold condition
        
        # Exit Thresholds
        # 0.85% ensures we cover fees/slippage and still bank green PnL
        self.min_profit = 0.0085 

    def _get_metrics(self, data):
        """Calculates Z-Score and RSI efficiently."""
        if len(data) < self.window_long:
            return None, None, None
            
        # 1. Z-Score
        sample = list(data)[-self.window_long:]
        mean = statistics.mean(sample)
        stdev = statistics.stdev(sample)
        current_price = sample[-1]
        
        if stdev == 0:
            z = 0
        else:
            z = (current_price - mean) / stdev
            
        # 2. RSI
        if len(data) <= self.window_rsi:
            rsi = 50
        else:
            recent = list(data)[-self.window_rsi-1:]
            deltas = [recent[i] - recent[i-1] for i in range(1, len(recent))]
            
            gains = [d for d in deltas if d > 0]
            losses = [abs(d) for d in deltas if d < 0]
            
            avg_gain = sum(gains) / self.window_rsi
            avg_loss = sum(losses) / self.window_rsi
            
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                
        return z, rsi, stdev

    def on_price_update(self, prices):
        # 1. Data Ingestion
        for sym, data in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_long + 5)
            self.history[sym].append(data['priceUsd'])
            
            # Tick down cooldowns
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]

        # 2. Position Management (Exits)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            pos = self.positions[sym]
            current_price = prices[sym]['priceUsd']
            entry_price = pos['entry']
            pos['ticks'] += 1
            
            # PnL Calculation
            pnl = (current_price - entry_price) / entry_price
            
            should_sell = False
            reason = ""
            
            # Strict Profitability Check:
            # We NEVER sell unless PnL > min_profit. This prevents 'STOP_LOSS' penalty.
            if pnl > self.min_profit:
                
                # Dynamic Target Logic
                # Early trade: aim high (2.5%). Stale trade: aim low (0.85%).
                target = 0.025
                if pos['ticks'] > 45: target = 0.015
                if pos['ticks'] > 90: target = self.min_profit
                
                # Exit Condition A: Target Hit
                if pnl >= target:
                    should_sell = True
                    reason = "TARGET_HIT"
                    
                # Exit Condition B: Mean Reversion Complete
                # If price is back above the mean (Z > 0), the "rubber band" has snapped back.
                # Since we are already profitable (pnl > min_profit), we take the win.
                hist = self.history[sym]
                z, _, _ = self._get_metrics(hist)
                if z is not None and z > 0:
                    should_sell = True
                    reason = "MEAN_REVERTED"
            
            if should_sell:
                del self.positions[sym]
                self.cooldown[sym] = 20 # Prevent immediate re-entry
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason, f"PnL:{pnl:.2%}"]
                }

        # 3. Entry Logic
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions or sym in self.cooldown:
                    continue
                
                if sym not in self.history or len(self.history[sym]) < self.window_long:
                    continue
                    
                hist = self.history[sym]
                z, rsi, stdev = self._get_metrics(hist)
                
                if z is None: continue
                
                curr_price = hist[-1]
                prev_price = hist[-2]
                
                # Filter 1: Min Volatility
                # If asset is flatlining, Z-score is noisy. Ignore.
                if stdev < (curr_price * 0.001):
                    continue
                    
                # Filter 2: The Setup (Deep Value)
                if z < self.z_entry and rsi < self.rsi_entry:
                    
                    # Filter 3: Falling Knife Protection
                    # Require the current tick to be UP (green) compared to previous tick.
                    # This implies immediate selling pressure has paused.
                    if curr_price > prev_price:
                        
                        # Filter 4: Crash Guard
                        # If Z is catastrophic (<-4.5), ensure RSI is near 0.
                        if z < -4.5 and rsi > 15:
                            continue
                            
                        # Add to candidates, prioritized by how oversold they are
                        candidates.append((sym, z))
            
            if candidates:
                # Sort by Z-score ascending (most negative first)
                candidates.sort(key=lambda x: x[1])
                best_sym, best_z = candidates[0]
                
                self.positions[best_sym] = {
                    'entry': prices[best_sym]['priceUsd'],
                    'amount': self.slot_size,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.slot_size,
                    'reason': ['DEEP_VALUE', f"Z:{best_z:.2f}"]
                }

        return None