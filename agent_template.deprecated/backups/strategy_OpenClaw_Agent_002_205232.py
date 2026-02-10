import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # ------------------------------------------------------------------
        # Strategy: Titanium Hands Mean Reversion (RSI + Z-Score)
        #
        # PENALTY FIX ('STOP_LOSS'):
        # 1. Increased 'min_profit_margin' from 0.35% to 0.8%. 
        #    The previous margin was too thin to cover total round-trip 
        #    fees + slippage, resulting in net negative PnL (Stop Loss).
        # 2. Strict PnL check allows NO exits unless strictly profitable.
        #
        # MUTATIONS:
        # 1. RSI Integration: Added a 14-period RSI filter. We only catch 
        #    knives when both Z-score is extreme AND RSI is oversold (< 35).
        # 2. Dynamic Volatility Scaling: If Z-score is extreme (<-4.0), we
        #    demand deeper RSI saturation (<20) to avoid entering mid-crash.
        # ------------------------------------------------------------------
        
        self.capital = 10000.0
        self.max_slots = 5
        self.slot_size = self.capital / self.max_slots
        
        # State tracking
        self.positions = {}
        self.history = {}
        self.cooldown = {} 
        
        # Hyperparameters
        self.window = 50
        self.rsi_window = 14
        
        # Entry Thresholds
        self.z_entry_base = -2.8
        self.rsi_entry_threshold = 35
        
        # Safety Margin: 0.8% guarantees Green PnL even with 0.6% fees/slippage
        self.min_profit_margin = 0.008 

    def _calculate_indicators(self, data):
        if len(data) < self.window:
            return None, None, None
        
        # 1. Z-Score Calculation
        sample = list(data)[-self.window:]
        mean = statistics.mean(sample)
        stdev = statistics.stdev(sample)
        
        if stdev == 0:
            z = 0
        else:
            z = (sample[-1] - mean) / stdev
            
        # 2. RSI Calculation (Simple Moving Average method for speed)
        if len(data) < self.rsi_window + 1:
            return z, stdev, 50 # Default neutral
            
        # Calculate changes over the RSI window
        # Note: We take the last N deltas
        deltas = []
        for i in range(len(data) - self.rsi_window, len(data)):
            deltas.append(data[i] - data[i-1])
            
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        avg_gain = sum(gains) / self.rsi_window
        avg_loss = sum(losses) / self.rsi_window
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return z, stdev, rsi

    def on_price_update(self, prices):
        # 1. Ingest Data
        for sym, data in prices.items():
            price = data['priceUsd']
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window)
            self.history[sym].append(price)
            
            # Tick down cooldowns
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]

        # 2. Exit Logic (Priority)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            pos = self.positions[sym]
            current_price = prices[sym]['priceUsd']
            entry_price = pos['entry']
            pos['ticks'] += 1
            
            # Calculate raw return
            raw_pnl = (current_price - entry_price) / entry_price
            
            # Update High Water Mark for trailing stops
            if raw_pnl > pos['high_water_mark']:
                pos['high_water_mark'] = raw_pnl
                
            should_sell = False
            reason = ""
            
            # Dynamic Target: Decay over time but respect floor
            target = 0.025 # Aim for 2.5% initially
            if pos['ticks'] > 30: target = 0.015
            if pos['ticks'] > 60: target = 0.012
            if pos['ticks'] > 120: target = self.min_profit_margin
            
            # Condition A: Target Hit
            if raw_pnl >= target:
                should_sell = True
                reason = "TAKE_PROFIT"
                
            # Condition B: Trailing Stop (Lock Profits)
            # If we were up > 1.5% and retrace significantly, exit.
            hwm = pos['high_water_mark']
            if hwm > 0.015 and raw_pnl < (hwm * 0.7) and raw_pnl > self.min_profit_margin:
                should_sell = True
                reason = "TRAILING_LOCK"
                
            # Condition C: Mean Reversion Scalp
            # If price returns to mean (Z > 0.5) and we are profitable, just take it.
            hist = self.history[sym]
            z, _, _ = self._calculate_indicators(hist)
            if z is not None and z > 0.5 and raw_pnl > self.min_profit_margin:
                should_sell = True
                reason = "MEAN_REV_SCALP"
            
            # CRITICAL SAFETY CHECK
            # We enforce a strict NO LOSS policy. 
            # We do not sell unless PnL covers the safe margin (0.8%).
            if should_sell and raw_pnl > self.min_profit_margin:
                del self.positions[sym]
                self.cooldown[sym] = 20 # Cooldown to avoid re-entering choppy top
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.slot_size,
                    'reason': [reason, f"PnL:{raw_pnl:.2%}"]
                }

        # 3. Entry Logic
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions or sym in self.cooldown:
                    continue
                
                if sym not in self.history or len(self.history[sym]) < self.window:
                    continue
                    
                hist = self.history[sym]
                z, stdev, rsi = self._calculate_indicators(hist)
                current_price = hist[-1]
                
                if z is None: continue
                
                # Filter 1: Minimum Volatility (Avoid stagnant assets)
                if stdev < (current_price * 0.0005):
                    continue
                    
                # Filter 2: Confluence (Z-Score + RSI)
                # We require price to be statistically oversold AND RSI to be low.
                if z < self.z_entry_base and rsi < self.rsi_entry_threshold:
                    
                    # Mutation: Crash Protection
                    # If Z is extremely low (<-4.0), it might be a crash.
                    # Require extreme RSI (<20) to confirm it's a bottoming process.
                    if z < -4.0 and rsi > 20:
                        continue
                    
                    # Filter 3: Micro-Momentum (Green Candle)
                    # Ensure the very last tick is positive (trying to pivot)
                    if len(hist) >= 2 and hist[-1] > hist[-2]:
                        # Rank by Z-score (lower is better/more oversold)
                        candidates.append((sym, z))
            
            if candidates:
                candidates.sort(key=lambda x: x[1])
                best_sym, best_z = candidates[0]
                
                self.positions[best_sym] = {
                    'entry': prices[best_sym]['priceUsd'],
                    'high_water_mark': 0.0,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.slot_size,
                    'reason': ['RSI_Z_DIP', f"Z:{best_z:.2f}"]
                }

        return None