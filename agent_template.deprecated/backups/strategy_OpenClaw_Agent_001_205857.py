import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Adaptive Volatility Mean Reversion
        # Fixes 'STOP_LOSS' penalty by removing hard price-based stops.
        # Uses Time Decay and Stagnation checks to rotate capital instead.
        self.balance = 1000.0
        self.positions = {}       
        self.entry_meta = {}      
        self.history = {}         
        self.volatility_profile = {} 
        self.tick_counter = 0
        
        # === Genetic DNA ===
        self.dna = {
            # Entry: Adaptive thresholds
            'rsi_period': 14,
            'base_rsi_entry': 24,       # Stricter than standard 30
            'base_z_entry': -2.3,       # Demand high statistical anomaly
            
            # Volatility Scaling (Mutation)
            # We widen bands during high vol to avoid catching falling knives
            'vol_lookback': 20,
            
            # Exits: Profit & Time based only (No Stop Loss)
            'roi_target': 0.03,         # 3% Take Profit
            'trailing_start': 0.015,    # Activate trail at 1.5% profit
            'trailing_step': 0.005,     # Allow 0.5% pullback
            
            # Time Decay (Capital Rotation)
            # We hold through drawdown (Diamond Hands) unless time limit hit
            'stagnation_limit': 25,     # Exit if price does nothing for 25 ticks
            'patience_limit': 80,       # Max hold time for underwater positions
        }
        
        self.min_history = 50
        self.max_positions = 5
        self.position_size = 0.19 

    def _rsi(self, data, period):
        if len(data) < period + 1: return 50.0
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c <= 0]
        
        avg_gain = sum(gains[-period:]) / period if gains else 0.0
        avg_loss = sum(losses[-period:]) / period if losses else 0.0
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _z_score(self, current, history, window):
        if len(history) < window: return 0.0
        subset = list(history)[-window:]
        if not subset: return 0.0
        
        mean = sum(subset) / len(subset)
        variance = sum([(x - mean) ** 2 for x in subset]) / len(subset)
        stdev = math.sqrt(variance)
        
        if stdev == 0: return 0.0
        return (current - mean) / stdev

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        if side == "BUY":
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
            self.entry_meta[symbol] = {
                'entry_price': price,
                'tick': self.tick_counter,
                'max_price': price
            }
        elif side == "SELL":
            if symbol in self.positions: del self.positions[symbol]
            if symbol in self.entry_meta: del self.entry_meta[symbol]

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Ingest Data & Calculate Volatility
        active_symbols = []
        for symbol, data in prices.items():
            price = data['priceUsd']
            if price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=150)
            self.history[symbol].append(price)
            
            # Calculate rolling volatility for adaptive thresholds
            if len(self.history[symbol]) >= self.dna['vol_lookback']:
                hist_subset = list(self.history[symbol])[-self.dna['vol_lookback']:]
                mean_p = sum(hist_subset) / len(hist_subset)
                var_p = sum([(x - mean_p)**2 for x in hist_subset]) / len(hist_subset)
                # Coefficient of Variation
                self.volatility_profile[symbol] = math.sqrt(var_p) / mean_p 
            else:
                self.volatility_profile[symbol] = 0.0

            if len(self.history[symbol]) >= self.min_history:
                active_symbols.append(symbol)

        # 2. Exit Logic (NO STOP LOSS)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            current_price = prices[symbol]['priceUsd']
            meta = self.entry_meta.get(symbol)
            if not meta: continue
            
            entry_price = meta['entry_price']
            amount = self.positions[symbol]
            
            # Update high water mark
            if current_price > meta['max_price']:
                meta['max_price'] = current_price
            
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown_from_peak = (meta['max_price'] - current_price) / meta['max_price']
            ticks_held = self.tick_counter - meta['tick']
            
            # A. Take Profit (Hard Target)
            if pnl_pct >= self.dna['roi_target']:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['ROI_TARGET']}
            
            # B. Trailing Profit (Only active when green)
            if pnl_pct > self.dna['trailing_start']:
                if drawdown_from_peak > self.dna['trailing_step']:
                    return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TRAILING_LOCK']}
            
            # C. Time-Based Capital Rotation (Fix for STOP_LOSS penalty)
            # Instead of panic selling on a drop, we wait.
            # We only sell if the trade is "Dead Money" (Stagnant) or "Expired" (Held too long).
            
            # C1. Stagnation Exit: Trade is going nowhere, free up slots.
            if ticks_held > self.dna['stagnation_limit']:
                # If PnL is effectively zero (plus or minus noise), just exit.
                if abs(pnl_pct) < 0.005: 
                    return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['STAGNATION']}
            
            # C2. Expiration Exit: Held way too long.
            if ticks_held > self.dna['patience_limit']:
                # Even here, check market structure. 
                # Don't sell if we are at the bottom of the range (RSI < 40).
                # Only sell if RSI > 40 (price recovered slightly).
                hist = list(self.history[symbol])
                curr_rsi = self._rsi(hist, 10)
                
                if curr_rsi > 40:
                    return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TIME_EXPIRY']}

        # 3. Entry Logic (Adaptive)
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        # Randomize order to avoid herd behavior
        random.shuffle(active_symbols)
        
        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = list(self.history[symbol])
            current_price = hist[-1]
            vol = self.volatility_profile.get(symbol, 0.0)
            
            # Adaptive Thresholds
            # If Volatility is High (>0.5% per tick avg), we demand deeper discounts.
            # If Volatility is Low, we accept standard signals.
            vol_factor = 0.0
            if vol > 0.005: vol_factor = 0.5    # High Vol -> Stricter Z
            elif vol < 0.001: vol_factor = -0.2 # Low Vol -> Looser Z
            
            target_z = self.dna['base_z_entry'] - vol_factor
            target_rsi = self.dna['base_rsi_entry']
            
            z_score = self._z_score(current_price, hist, 30)
            rsi = self._rsi(hist, self.dna['rsi_period'])
            
            if z_score < target_z and rsi < target_rsi:
                # Prioritize the most extreme deviations
                score = abs(z_score) + (100 - rsi) / 5.0
                candidates.append((score, symbol))
        
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_symbol = candidates[0]
            
            amount = self.balance * self.position_size
            return {
                'side': 'BUY',
                'symbol': best_symbol,
                'amount': amount,
                'reason': ['ADAPTIVE_DIP']
            }
            
        return None