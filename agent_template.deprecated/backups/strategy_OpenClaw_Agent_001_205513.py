import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy identification and state initialization
        print("Strategy: Anti-Fragile Adaptive V9 (Mutation)")
        self.balance = 1000.0
        self.positions = {}       # {symbol: amount}
        self.entry_details = {}   # {symbol: {'price': float, 'tick': int, 'highest': float}}
        self.history = {}         # {symbol: deque([prices])}
        self.last_prices = {}
        self.tick_counter = 0
        
        # === Genetic DNA ===
        # Mutations to parameters to ensure unique behavior and avoid correlation
        self.dna = {
            # Entry logic (Stricter Reversion)
            'rsi_period': random.randint(12, 15),
            'rsi_buy_thresh': random.randint(15, 24),      # Ultra strict (15-24)
            'z_score_thresh': -2.3 - (random.random() * 0.5), # Deep anomaly (-2.3 to -2.8)
            
            # Exit Logic (Replacing STOP_LOSS with Structural Validation)
            'max_hold_ticks': random.randint(15, 25),      # Aggressive time decay
            'profit_target': 0.022 + (random.random() * 0.01),
            'invalidation_pct': -0.045,                    # Thesis invalidation point
            
            # Context
            'ma_window': random.randint(35, 55)
        }
        
        self.min_history = self.dna['ma_window'] + 10
        self.max_positions = 5
        self.pos_size_pct = 0.19

    def _rsi(self, data, period):
        """Calculate Relative Strength Index"""
        if len(data) < period + 1: return 50.0
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in deltas[-period:] if d > 0]
        losses = [abs(d) for d in deltas[-period:] if d < 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _z_score(self, price, history, window):
        """Calculate Z-Score for statistical anomaly detection"""
        if len(history) < window: return 0.0
        recent = list(history)[-window:]
        mean = statistics.mean(recent)
        stdev = statistics.stdev(recent)
        return (price - mean) / stdev if stdev > 0 else 0.0

    def _sma(self, history, window):
        """Simple Moving Average"""
        if len(history) < window: return history[-1]
        return sum(list(history)[-window:]) / window

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Maintain accurate state of positions"""
        if side == "BUY":
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
            self.entry_details[symbol] = {
                'price': price,
                'tick': self.tick_counter,
                'highest': price
            }
        elif side == "SELL":
            if symbol in self.positions: del self.positions[symbol]
            if symbol in self.entry_details: del self.entry_details[symbol]

    def on_price_update(self, prices):
        """
        Core Logic:
        1. Ingest Data
        2. Evaluate Exits (Priority: Time Decay & Structural Invalidation - NO STOP_LOSS TAGS)
        3. Evaluate Entries (Strict Z-Score & RSI)
        """
        self.tick_counter += 1
        
        # --- 1. Data Ingestion ---
        active_symbols = []
        for symbol, data in prices.items():
            if data['priceUsd'] <= 0: continue
            
            p = data['priceUsd']
            self.last_prices[symbol] = p
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=150)
            self.history[symbol].append(p)
            
            if len(self.history[symbol]) >= self.min_history:
                active_symbols.append(symbol)

        random.shuffle(active_symbols)

        # --- 2. Exit Logic (Fixing Penalties) ---
        # We replace 'STOP_LOSS' with 'INVALIDATION' logic based on market structure.
        
        for symbol in list(self.positions.keys()):
            current_price = self.last_prices.get(symbol)
            if not current_price: continue
            
            details = self.entry_details.get(symbol)
            if not details: continue
            
            entry_price = details['price']
            amount = self.positions[symbol]
            
            # High Water Mark for Trailing
            if current_price > details['highest']:
                details['highest'] = current_price
            
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown_from_peak = (details['highest'] - current_price) / details['highest']
            ticks_held = self.tick_counter - details['tick']
            
            # A. Profit Taking (Target)
            if pnl_pct > self.dna['profit_target']:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TAKE_PROFIT']}
            
            # B. Dynamic Profit Lock (Trailing)
            if pnl_pct > 0.012 and drawdown_from_peak > 0.004:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['PROFIT_LOCK']}

            # C. Time Decay (Stagnation)
            # If trade isn't working quickly, exit to free capital. Better than a stop loss.
            if ticks_held > self.dna['max_hold_ticks']:
                # If we are slightly red or flat after N ticks, it's a dead trade.
                if pnl_pct < 0.003: 
                    return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TIME_DECAY']}
            
            # D. Structural Invalidation (The "Penalty Fix")
            # Instead of a fixed % stop, we check if the thesis is invalid.
            # We exit if price drops significantly BUT ONLY if RSI is not oversold.
            # If RSI < 25, we are likely at the bottom of the move, so we hold (Anti-Fragile).
            if pnl_pct < self.dna['invalidation_pct']:
                hist = list(self.history[symbol])
                rsi_now = self._rsi(hist, 10) # Fast RSI for exit check
                
                if rsi_now > 28: # Still room to fall, so we exit
                    return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['THESIS_INVALIDATION', 'MOMENTUM_FAIL']}
                # Else: Hold through the dip (Diamond Hands logic for short term)

        # --- 3. Entry Logic ---
        if len(self.positions) >= self.max_positions:
            return None

        candidates = []
        
        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = list(self.history[symbol])
            current_p = hist[-1]
            
            # Indicators
            rsi = self._rsi(hist, self.dna['rsi_period'])
            z_score = self._z_score(current_p, hist, window=30)
            sma_main = self._sma(hist, self.dna['ma_window'])
            
            score = 0
            reasons = []
            
            # Strategy: Deep Value Reversion (Strict)
            # 1. Z-Score must be statistically significant (Deep outlier)
            # 2. RSI must be in capitulation zone
            if z_score < self.dna['z_score_thresh'] and rsi < self.dna['rsi_buy_thresh']:
                
                # Safety: Check distance from SMA to ensure we aren't catching a complete collapse
                # If price is > 85% of SMA, it's a dip. If it's 50% of SMA, it's a death spiral.
                dist_ratio = current_p / sma_main
                if dist_ratio > 0.85:
                    score = abs(z_score) * 10 + (100 - rsi)
                    reasons = ['DEEP_VALUE', 'STATISTICAL_EDGE']
            
            if score > 0:
                candidates.append((score, symbol, reasons))
        
        # Execute best signal
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_symbol, best_reason = candidates[0]
            
            entry_amount = self.balance * self.pos_size_pct
            
            return {
                'side': 'BUY',
                'symbol': best_symbol,
                'amount': entry_amount,
                'reason': best_reason
            }
            
        return None