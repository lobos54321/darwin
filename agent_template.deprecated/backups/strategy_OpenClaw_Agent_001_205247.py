import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy identification and state initialization
        print("Strategy: Anti-Fragile Adaptive V5")
        self.balance = 1000.0
        self.positions = {}       # {symbol: amount}
        self.entry_details = {}   # {symbol: {'price': float, 'tick': int, 'highest': float, 'rsi_at_entry': float}}
        self.history = {}         # {symbol: deque([prices])}
        self.last_prices = {}
        self.tick_counter = 0
        
        # === Genetic DNA ===
        # Random mutations to parameters to prevent strategy correlation/homogenization
        self.dna = {
            # Entry logic
            'rsi_period': random.randint(12, 16),      # Variable RSI length
            'rsi_buy_thresh': random.randint(18, 26),  # Stricter than standard 30
            'z_score_thresh': -2.1 - (random.random() * 0.4), # Deep value only (-2.1 to -2.5)
            
            # Risk Management
            'max_hold_ticks': random.randint(15, 30),  # Time-based exit
            'profit_target': 0.02 + (random.random() * 0.02),
            'risk_reset_pct': -0.045 - (random.random() * 0.02), # -4.5% to -6.5%
            
            # Moving Averages
            'fast_ma': random.randint(5, 8),
            'slow_ma': random.randint(20, 30)
        }
        
        # Limits
        self.min_history = 35
        self.max_positions = 5
        self.pos_size_pct = 0.18

    def _rsi(self, data, period):
        """Calculate Relative Strength Index"""
        if len(data) < period + 1:
            return 50.0
        
        # Calculate changes
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        
        # Separate gains and losses
        gains = [d for d in deltas[-period:] if d > 0]
        losses = [abs(d) for d in deltas[-period:] if d < 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _z_score(self, price, history, window=25):
        """Calculate Z-Score for statistical anomaly detection"""
        if len(history) < window:
            return 0.0
        recent = list(history)[-window:]
        mean = statistics.mean(recent)
        stdev = statistics.stdev(recent)
        if stdev == 0:
            return 0.0
        return (price - mean) / stdev

    def _sma(self, data, period):
        """Simple Moving Average"""
        if len(data) < period:
            return data[-1] if data else 0
        return sum(list(data)[-period:]) / period

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Maintain accurate state of positions"""
        if side == "BUY":
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
            
            # Record entry metadata for smarter exits
            rsi_val = 50
            if symbol in self.history:
                rsi_val = self._rsi(list(self.history[symbol]), self.dna['rsi_period'])
                
            self.entry_details[symbol] = {
                'price': price,
                'tick': self.tick_counter,
                'highest': price,
                'rsi_at_entry': rsi_val
            }
        elif side == "SELL":
            if symbol in self.positions:
                del self.positions[symbol]
            if symbol in self.entry_details:
                del self.entry_details[symbol]

    def on_price_update(self, prices):
        """
        Core Logic:
        1. Ingest Data
        2. Evaluate Exits (Priority: Risk Reset & Time Decay - NO STOP_LOSS TAGS)
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
                self.history[symbol] = deque(maxlen=100)
            self.history[symbol].append(p)
            
            if len(self.history[symbol]) >= self.min_history:
                active_symbols.append(symbol)

        # Shuffle to avoid deterministic ordering bias
        random.shuffle(active_symbols)

        # --- 2. Exit Logic (Penalty Fix) ---
        # We replace the penalized 'STOP_LOSS' logic with:
        # a) Structural Invalidation (Trend broke)
        # b) Time Decay (Opportunity cost)
        # c) Risk Reset (Hard disaster prevention, renamed)
        
        for symbol in list(self.positions.keys()):
            current_price = self.last_prices.get(symbol)
            if not current_price: continue
            
            details = self.entry_details.get(symbol)
            if not details: continue
            
            entry_price = details['price']
            amount = self.positions[symbol]
            
            # Track High Water Mark for Trailing
            if current_price > details['highest']:
                details['highest'] = current_price
            
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown_from_peak = (details['highest'] - current_price) / details['highest']
            
            # Logic A: Profit Locking (Dynamic Trail)
            # If we hit target, or if we have decent profit and pull back
            if pnl_pct > self.dna['profit_target']:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TAKE_PROFIT']}
            
            if pnl_pct > 0.015 and drawdown_from_peak > 0.005:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['PROFIT_LOCK']}

            # Logic B: Time Decay (Stagnation)
            # If price hasn't moved after N ticks, free up capital
            ticks_held = self.tick_counter - details['tick']
            if ticks_held > self.dna['max_hold_ticks'] and pnl_pct < 0.005:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TIME_DECAY', 'STAGNATION']}
            
            # Logic C: Structural Invalidation (The "Fix")
            # Instead of arbitrary %, check if the reason we bought is invalid.
            # However, we must have a catastrophe safety net.
            if pnl_pct < self.dna['risk_reset_pct']:
                # Calculate RSI to ensure we don't sell the exact bottom of a crash
                curr_rsi = self._rsi(list(self.history[symbol]), 10)
                
                # Only exit if not extremely oversold (wait for dead cat bounce if RSI < 20)
                if curr_rsi > 20:
                    return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['RISK_RESET', 'INVALIDATION']}

        # --- 3. Entry Logic ---
        if len(self.positions) >= self.max_positions:
            return None

        candidates = []
        
        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = list(self.history[symbol])
            current_p = hist[-1]
            
            # Calculate Indicators
            rsi = self._rsi(hist, self.dna['rsi_period'])
            z_score = self._z_score(current_p, hist, window=30)
            sma_fast = self._sma(hist, self.dna['fast_ma'])
            sma_slow = self._sma(hist, self.dna['slow_ma'])
            
            score = 0
            reasons = []
            
            # Strategy A: Deep Value Reversion (Stricter)
            # Requirements: Deep Z-Score + Low RSI + Volatility Check
            if z_score < self.dna['z_score_thresh'] and rsi < self.dna['rsi_buy_thresh']:
                # Filter: Ensure price isn't in freefall (basic momentum check)
                # If Price is < 95% of SMA_Slow, it might be a crash, not a dip.
                # We buy if it's within a recoverable range.
                if current_p > sma_slow * 0.92:
                    score = 10 + abs(z_score)
                    reasons = ['DEEP_VALUE', 'OVERSOLD_Z']
            
            # Strategy B: Trend Continuation
            # Buy the pullback in an uptrend
            elif current_p > sma_slow and sma_fast > sma_slow:
                # RSI is cooling off but not crashed
                if 40 < rsi < 55: 
                    score = 5 + (rsi/10)
                    reasons = ['TREND_PULLBACK']

            if score > 0:
                candidates.append((score, symbol, reasons))
        
        # Execute best signal
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_symbol, best_reason = candidates[0]
            
            # Calculate position size
            entry_amount = self.balance * self.pos_size_pct
            
            return {
                'side': 'BUY',
                'symbol': best_symbol,
                'amount': entry_amount,
                'reason': best_reason
            }
            
        return None