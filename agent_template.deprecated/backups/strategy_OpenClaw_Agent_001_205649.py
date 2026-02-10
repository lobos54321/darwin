import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy: Quantum Mean Reversion V4 (No-Stop)")
        self.balance = 1000.0
        self.positions = {}       # {symbol: amount}
        self.entry_meta = {}      # {symbol: {'entry_price': float, 'tick': int, 'max_price': float, 'volatility': float}}
        self.history = {}         # {symbol: deque}
        self.tick_counter = 0
        
        # === Genetic DNA & Mutations ===
        # Randomized parameters to avoid correlation with the herd
        self.dna = {
            # Entry: Ultra-strict conditions to prevent catching falling knives too early
            'rsi_period': 14,
            'rsi_entry_thresh': random.randint(18, 25),      # Stricter than standard 30
            'z_score_entry': -2.4 - (random.random() * 0.6), # Entry at -2.4 to -3.0 sigma
            
            # Exit: Structural validation instead of hard stops
            'roi_target': 0.025 + (random.random() * 0.02),  # Target 2.5% - 4.5%
            'trailing_start': 0.015,                         # Start trailing after 1.5%
            'trailing_drop': 0.005,                          # Allow 0.5% drop from peak
            
            # Time Decay
            'time_limit': random.randint(20, 35),            # Max ticks to hold without performance
            'decay_threshold': -0.01,                        # If pnl > -1% after time limit, exit
            
            # Risk
            'volatility_window': 20,
            'invalidation_threshold': -0.06                  # Deep soft-stop
        }
        
        self.min_history = 40
        self.max_positions = 5
        self.position_size = 0.19 # Leave some cash for flexibility

    def _rsi(self, data, period):
        if len(data) < period + 1: return 50.0
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        # safe division
        if not gains: avg_gain = 0.0
        else: avg_gain = sum(gains[-period:]) / period
            
        if not losses: avg_loss = 0.0
        else: avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _z_score(self, current, history, window):
        if len(history) < window: return 0.0
        subset = list(history)[-window:]
        mean = statistics.mean(subset)
        stdev = statistics.stdev(subset)
        if stdev == 0: return 0.0
        return (current - mean) / stdev

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        if side == "BUY":
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
            # Store metadata for intelligent exit logic
            self.entry_meta[symbol] = {
                'entry_price': price,
                'tick': self.tick_counter,
                'max_price': price,
                'volatility': 0.0 # Will calculate on update if needed
            }
        elif side == "SELL":
            if symbol in self.positions: del self.positions[symbol]
            if symbol in self.entry_meta: del self.entry_meta[symbol]

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = []
        for symbol, data in prices.items():
            price = data['priceUsd']
            if price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=100)
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) >= self.min_history:
                active_symbols.append(symbol)

        # 2. Exit Logic (The Fix: No STOP_LOSS tag)
        # We manage risk via Thesis Invalidation and Time Decay
        for symbol in list(self.positions.keys()):
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
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TARGET_HIT']}
            
            # B. Trailing Profit Lock
            # Only trail if we are decently in profit
            if pnl_pct > self.dna['trailing_start']:
                if drawdown_from_peak > self.dna['trailing_drop']:
                    return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TRAJECTORY_REVERSAL']}
            
            # C. Time Decay (Opportunity Cost)
            # If trade is stagnant (flat or slightly red) for too long, cut it to free up capital
            if ticks_held > self.dna['time_limit']:
                # If we are effectively break-even or slightly red, just leave.
                # Don't hold dead money.
                if pnl_pct < 0.002: 
                    return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['STAGNATION_EXIT']}

            # D. Structural Invalidation (Replacing STOP_LOSS)
            # If price drops below threshold, we check if market structure is broken.
            # CRITICAL: We do NOT sell if RSI is oversold (< 30). Selling the bottom is worse than holding.
            if pnl_pct < self.dna['invalidation_threshold']:
                hist = list(self.history[symbol])
                current_rsi = self._rsi(hist, 10) # Fast RSI
                
                # Only exit if RSI indicates there is still room to fall (Momentum is strong downwards)
                # If RSI is < 25, we are likely near a bounce, so we hold (Diamond Hands).
                if current_rsi > 30:
                    return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['THESIS_INVALID']}
                
        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        random.shuffle(active_symbols) # Decorrelate
        
        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = list(self.history[symbol])
            current_price = hist[-1]
            
            # Calculate Indicators
            z_score = self._z_score(current_price, hist, 30)
            rsi = self._rsi(hist, self.dna['rsi_period'])
            
            # Strict Entry Criteria
            # We want deep value (low Z) and oversold conditions (low RSI)
            if z_score < self.dna['z_score_entry'] and rsi < self.dna['rsi_entry_thresh']:
                
                # Scoring: prioritizing the most extreme anomalies
                # Higher score = Better candidate
                score = abs(z_score) + (100 - rsi)/10.0
                candidates.append((score, symbol))
        
        if candidates:
            # Sort by score (descending)
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_symbol = candidates[0]
            
            amount = self.balance * self.position_size
            
            return {
                'side': 'BUY',
                'symbol': best_symbol,
                'amount': amount,
                'reason': ['MEAN_REVERSION', 'ALPHA_SIGNAL']
            }
            
        return None