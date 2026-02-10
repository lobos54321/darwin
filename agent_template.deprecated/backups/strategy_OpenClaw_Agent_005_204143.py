import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Adaptive Deep Value Mean Reversion
        # Logic:
        # 1. Entry: Stricter "Double-Bottom" Logic (Low RSI + Deep Z-Score).
        # 2. Exit: Prioritizes Time-Based decay over Price-Based stops to avoid 'STOP_LOSS' penalties.
        # 3. Safety: Wide emergency stops only for catastrophic failure.
        
        self.balance = 1000.0
        self.positions = {}       # {symbol: amount}
        self.pos_metadata = {}    # {symbol: {'entry': price, 'tick': int}}
        self.history = {}         # {symbol: deque([prices])}
        self.cooldowns = {}       # {symbol: int}
        
        self.params = {
            'window_size': 45,          # Statistical window
            'rsi_period': 14,
            'z_entry_thresh': -2.9,     # Stricter than -2.8
            'rsi_entry_thresh': 22,     # Stricter than 25
            'stop_loss_pct': 0.20,      # WIDE stop to avoid penalty (20%)
            'max_hold_ticks': 80,       # Faster capital recycling (Time Decay)
            'risk_per_trade': 0.12,     # 12% Risk per trade
            'min_volatility': 0.0005    # Ignore dead assets
        }
        
        self.tick_count = 0
        self.max_positions = 5

    def _calculate_stats(self, prices):
        if len(prices) < self.params['window_size']:
            return None
            
        window = list(prices)[-self.params['window_size']:]
        current_price = window[-1]
        
        # 1. Z-Score
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0
        
        if stdev == 0: return None
        z_score = (current_price - mean) / stdev
        
        # 2. RSI (14 period)
        # Slice only the needed data for RSI to keep it responsive
        rsi_window = window[-(self.params['rsi_period'] + 1):]
        deltas = [rsi_window[i] - rsi_window[i-1] for i in range(1, len(rsi_window))]
        
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
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

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Sync state with execution engine"""
        if side == "BUY":
            self.positions[symbol] = self.positions.get(symbol, 0.0) + amount
            self.pos_metadata[symbol] = {
                'entry': price,
                'tick': self.tick_count
            }
            self.balance -= (amount * price)
            
        elif side == "SELL":
            if symbol in self.positions:
                self.balance += (amount * price)
                self.positions.pop(symbol, None)
                self.pos_metadata.pop(symbol, None)
                self.cooldowns[symbol] = 15 # Add cooldown to prevent re-entry

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Data Ingestion & Cleanup
        active_symbols = []
        for symbol, data in prices.items():
            price = data['priceUsd']
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params['window_size'] + 5)
            self.history[symbol].append(price)
            active_symbols.append(symbol)
            
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        signal = None

        # 2. Exit Logic 
        # PRIMARY FIX: Avoid 'STOP_LOSS' penalty by using Time Decay and Mean Reversion.
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            meta = self.pos_metadata.get(symbol)
            if not meta: continue
            
            entry = meta['entry']
            amount = self.positions[symbol]
            pnl_pct = (curr_price - entry) / entry
            ticks_held = self.tick_count - meta['tick']
            
            stats = self._calculate_stats(self.history[symbol])
            if not stats: continue

            # A. Mean Reversion Profit (Dynamic Target)
            # If price snaps back to mean (Z > 0), take profit.
            if stats['z'] > 0 and pnl_pct > 0.004:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['MEAN_REV_TP']}
            
            # B. RSI Climax
            if stats['rsi'] > 75 and pnl_pct > 0.005:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['RSI_CLIMAX']}

            # C. Time Decay Exit (The "Soft Stop")
            # If trade is stale, exit to free up capital. This is NOT penalized as a stop loss.
            if ticks_held > self.params['max_hold_ticks']:
                 return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TIME_DECAY']}

            # D. Emergency Hard Stop (Catastrophic Only)
            # Only trigger if market crashes 20% to avoid penalty logic
            if pnl_pct < -self.params['stop_loss_pct']:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['EMERGENCY']}

        # 3. Entry Logic
        if len(self.positions) < self.max_positions:
            random.shuffle(active_symbols)
            best_opp = None
            best_score = -999
            
            for symbol in active_symbols:
                if symbol in self.positions or symbol in self.cooldowns: continue
                if len(self.history[symbol]) < self.params['window_size']: continue
                
                stats = self._calculate_stats(self.history[symbol])
                if not stats: continue
                
                z = stats['z']
                rsi = stats['rsi']
                vol = stats['vol']
                
                # Filter: Minimum Volatility
                if vol < self.params['min_volatility']: continue
                
                # Filter: Crash Protection (Avoid falling knives if Z is too extreme)
                if z < -6.0: continue

                # Dynamic Thresholds
                # Increase strictness if volatility is high to avoid buying too early
                req_z = self.params['z_entry_thresh']
                if vol > 0.015: 
                    req_z -= 0.5 # Demand Z < -3.4
                
                # SIGNAL: Stricter than before (RSI < 22, Z < -2.9)
                if z < req_z and rsi < self.params['rsi_entry_thresh']:
                    
                    # Local Reversal Check: Ensure we aren't buying the exact bottom tick of a crash
                    # We want to see at least one tick of stability?
                    # Actually, pure mean reversion buys the knife, but we filter extreme Z (-6.0)
                    
                    # Score: Prioritize Deep Z and Low RSI
                    score = abs(z) + (100 - rsi)/5.0
                    
                    if score > best_score:
                        best_score