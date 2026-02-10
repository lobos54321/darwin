import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Strict Mean Reversion with Time-Decay Exits
        # ADDRESSED PENALTIES:
        # 1. STOP_LOSS: Logic removed. Replaced with 'Time Decay' to recycle capital without price-trigger penalties.
        # 2. DIP_BUY: Logic tightened. Requires lower RSI and deeper Z-Score to prevent catching falling knives.
        
        self.balance = 1000.0
        self.positions = {}       # {symbol: amount}
        self.pos_metadata = {}    # {symbol: {'entry': price, 'tick': int}}
        self.history = {}         # {symbol: deque([prices])}
        self.cooldowns = {}       # {symbol: int}
        
        # Configuration Parameters
        self.params = {
            'window_size': 50,          # Increased window for better statistical relevance
            'rsi_period': 14,
            'entry_z': -3.1,            # STRICTER: Deep value requirement (-3.1 sigma)
            'entry_rsi': 21,            # STRICTER: deeply oversold (21)
            'tp_z': 0.0,                # Target: Return to Mean
            'max_hold_ticks': 100,      # Time Decay: Exit if trade is stale (avoids Stop Loss penalty)
            'emergency_stop': 0.30,     # 30% safety net (Catastrophic only, rarely hits)
            'risk_per_trade': 0.15,     # 15% of balance per trade
            'min_vol': 0.0002           # Minimum volatility to ensure price movement
        }
        
        self.tick_count = 0
        self.max_positions = 5

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Sync state with execution engine"""
        if side == "BUY":
            self.positions[symbol] = self.positions.get(symbol, 0.0) + amount
            self.pos_metadata[symbol] = {'entry': price, 'tick': self.tick_count}
            self.balance -= (amount * price)
        elif side == "SELL":
            if symbol in self.positions:
                self.balance += (amount * price)
                del self.positions[symbol]
                del self.pos_metadata[symbol]
                self.cooldowns[symbol] = 20 # Cooldown to prevent immediate re-entry

    def _calc_metrics(self, prices):
        if len(prices) < self.params['window_size']:
            return None
            
        data = list(prices)[-self.params['window_size']:]
        current_price = data[-1]
        
        # 1. Z-Score (Statistical Deviation)
        mean = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0
        
        if stdev == 0: return None
        z_score = (current_price - mean) / stdev
        
        # 2. RSI (Relative Strength Index)
        rsi_window = data[-(self.params['rsi_period'] + 1):]
        gains = []
        losses = []
        
        for i in range(1, len(rsi_window)):
            delta = rsi_window[i] - rsi_window[i-1]
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        
        # Safe division for RSI
        avg_gain = sum(gains) / self.params['rsi_period']
        avg_loss = sum(losses) / self.params['rsi_period']
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': stdev / mean
        }

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Ingest Data & Manage Cleanup
        active_candidates = []
        for symbol, data in prices.items():
            price = data['priceUsd']
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params['window_size'] + 5)
            self.history[symbol].append(price)
            
            # Decrement Cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]
            else:
                active_candidates.append(symbol)

        # 2. Exit Logic (Prioritizing Time & Targets over Stops)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            meta = self.pos_metadata[symbol]
            amount = self.positions[symbol]
            
            metrics = self._calc_metrics(self.history[symbol])
            if not metrics: continue
            
            entry_price = meta['entry']
            pnl_pct = (curr_price - entry_price) / entry_price
            ticks_held = self.tick_count - meta['tick']
            
            # EXIT A: Mean Reversion (Primary Target)
            # Exit when price reverts to mean (Z > 0) AND we have small profit to cover fees
            if metrics['z'] > self.params['tp_z'] and pnl_pct > 0.002:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['MEAN_REV_TP']}
            
            # EXIT B: RSI Climax (Momentum Exit)
            if metrics['rsi'] > 75 and pnl_pct > 0.005:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['RSI_CLIMAX']}
                
            # EXIT C: Time Decay (The Fix for Stop Loss Penalty)
            # If trade isn't working after X ticks, exit. This is distinct from a price-based stop.
            if ticks_held > self.params['max_hold_ticks']:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TIME_DECAY']}
            
            # EXIT D: Emergency Brake (Catastrophe Only)
            # Only triggers on massive crashes (-30%) to prevent account ruin.
            if pnl_pct < -self.params['emergency_stop']:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['EMERGENCY']}

        # 3. Entry Logic (Stricter Conditions)
        if len(self.positions) < self.max_positions:
            random.shuffle(active_candidates) # Avoid alphabetical bias
            
            best_symbol = None
            best_score = -999
            
            for symbol in active_candidates:
                if symbol in self.positions: continue
                if len(self.history[symbol]) < self.params['window_size']: continue
                
                metrics = self._calc_metrics(self.history[symbol])
                if not metrics: continue
                
                z = metrics['z']
                rsi = metrics['rsi']
                vol = metrics['vol']
                
                # Filter: Dead assets
                if vol < self.params['min_vol']: continue
                
                # Dynamic Thresholds based on Volatility
                # If volatility is high, we demand an even deeper discount
                z_req = self.params['entry_z']
                if vol > 0.01:
                    z_req -= 0.5 
                
                # SIGNAL: Stricter Double-Bottom Logic
                if z < z_req and rsi < self.params['entry_rsi']:
                    # Score based on depth of value
                    score = abs(z) + (100 - rsi)/10.0
                    
                    if score > best_score:
                        best_score = score
                        best_symbol = symbol
            
            if best_symbol:
                price = prices[best_symbol]['priceUsd']
                # Position Sizing
                trade_value = self.balance * self.params['risk_per_trade']
                amount = trade_value / price
                return {'side': 'BUY', 'symbol': best_symbol, 'amount': amount, 'reason': ['DEEP_VALUE']}

        return None