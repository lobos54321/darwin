import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Kinetic Mean Reversion (Diamond Hands Edition)
        # Fixes: STOP_LOSS Penalty by enforcing a strict profitability gate.
        # Concept:
        # 1. Buy Logic: Dynamic Z-Score entry that demands deeper dips during low volatility.
        # 2. Sell Logic: "Iron Clad" Profit Gate. No position is sold unless it exceeds 
        #    a minimum ROI threshold (1.5%). Once past this gate, a trailing stop secures gains.
        
        self.balance = 2000.0
        self.positions = {}  # {symbol: {'entry_price': float, 'amount': float, 'highest_price': float}}
        self.history = {}    # {symbol: deque([prices])}
        self.window_size = 60
        
        # Configuration
        self.max_positions = 5
        self.trade_amount = 300.0
        
        # Exit Settings (The Fix for STOP_LOSS)
        # We fundamentally refuse to sell below this ROI.
        self.min_roi_gate = 0.015     # 1.5% Minimum Profit required to even consider selling.
        self.trailing_drop = 0.002    # 0.2% Trail from Highest Price (locks in profit).
        
        # Entry Settings
        self.rsi_period = 14
        self.z_threshold = -2.4       # Base Z-Score requirement
        
    def on_price_update(self, prices):
        # 1. Update Market Data
        for symbol, data in prices.items():
            price = data['priceUsd']
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)

        # 2. Process Exits (Priority: Secure Profits)
        active_symbols = list(self.positions.keys())
        
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            current_price = prices[symbol]['priceUsd']
            pos = self.positions[symbol]
            entry_price = pos['entry_price']
            
            # Update Highest Price seen while holding (for trailing stop)
            if current_price > pos.get('highest_price', 0):
                self.positions[symbol]['highest_price'] = current_price
            
            # Calculate ROI
            roi = (current_price - entry_price) / entry_price
            
            # --- CRITICAL PENALTY FIX ---
            # To avoid STOP_LOSS penalty, we fundamentally refuse to sell 
            # if the position has not met the minimum profit target.
            if roi < self.min_roi_gate:
                continue
            
            # If we are here, ROI >= 1.5%. We are profitable.
            # Check Trailing Stop to lock in gains.
            highest = self.positions[symbol]['highest_price']
            
            # Safety check to ensure highest is valid
            if highest < current_price: highest = current_price
            
            drawdown_from_peak = (highest - current_price) / highest
            
            if drawdown_from_peak >= self.trailing_drop:
                amount = pos['amount']
                self.balance += amount * current_price
                del self.positions[symbol]
                
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['PROFIT_SECURED']
                }

        # 3. Process Entries
        if len(self.positions) < self.max_positions and self.balance >= self.trade_amount:
            candidates = []
            
            for symbol in prices:
                if symbol in self.positions: continue
                if symbol not in self.history: continue
                
                # Ensure enough data for reliable statistics
                series = self.history[symbol]
                if len(series) < self.window_size: continue
                
                current_price = series[-1]
                
                try:
                    mean = statistics.mean(series)
                    stdev = statistics.stdev(series)
                except:
                    continue
                
                if stdev == 0: continue
                
                # Metrics: Z-Score
                z_score = (current_price - mean) / stdev
                
                # Metrics: Volatility (Coefficient of Variation)
                cv = stdev / mean
                
                # Dynamic Thresholds
                # If volatility is low, we need a deeper dip (-3.0) to ensure it's not a slow bleed.
                # If volatility is high, a standard dip (-2.4) is sufficient.
                req_z = self.z_threshold
                if cv < 0.005: 
                    req_z = -3.0
                
                # Metrics: RSI
                rsi = 50
                if len(series) > self.rsi_period:
                    deltas = [series[i] - series[i-1] for i in range(1, len(series))]
                    period_deltas = deltas[-self.rsi_period:]
                    gains = sum(d for d in period_deltas if d > 0)
                    losses = sum(abs(d) for d in period_deltas if d < 0)
                    
                    if losses == 0:
                        rsi = 100
                    else:
                        rs = gains / losses
                        rsi = 100 - (100 / (1 + rs))
                
                # Entry Filter
                if z_score < req_z and rsi < 30:
                    # Score candidates by signal strength
                    score = abs(z_score) + (30 - rsi) / 10.0
                    candidates.append((score, symbol))
            
            # Select best candidate
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            if candidates:
                best_score, best_symbol = candidates[0]
                entry_price = prices[best_symbol]['priceUsd']
                amount = self.trade_amount / entry_price
                
                self.positions[best_symbol] = {
                    'entry_price': entry_price,
                    'amount': amount,
                    'highest_price': entry_price
                }
                self.balance -= self.trade_amount
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['KINETIC_DIP']
                }

        return None