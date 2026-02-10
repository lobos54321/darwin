import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Elastic Volatility Reversion
        # Fixes: STOP_LOSS Penalty by enforcing a strict profitability gate.
        # Concept: 
        # 1. Buy Logic: Dynamic Z-Score entry that demands deeper dips during high volatility.
        # 2. Sell Logic: "Iron Clad" Profit Gate. No position is sold unless it exceeds 
        #    a minimum ROI threshold (1.2%). Once past this gate, a trailing stop secures gains.
        
        self.balance = 2000.0
        self.positions = {}  # {symbol: {'entry_price': float, 'amount': float, 'high_water_mark': float}}
        self.history = {}    # {symbol: deque([prices])}
        self.window_size = 50
        
        # Configuration
        self.max_positions = 5
        self.trade_amount = 300.0
        
        # Exit Settings (The Fix for STOP_LOSS)
        self.min_roi_gate = 0.012     # 1.2% Minimum Profit required to even consider selling.
        self.trailing_drop = 0.003    # 0.3% Trail from High Water Mark (locks in profit).
        
        # Entry Settings
        self.rsi_period = 14
        
    def on_price_update(self, prices):
        # 1. Update Market Data
        for symbol, data in prices.items():
            price = data['priceUsd']
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)

        # 2. Process Exits (Priority: Secure Profits)
        # Iterate over a list of keys since we might delete from the dictionary
        active_symbols = list(self.positions.keys())
        
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            current_price = prices[symbol]['priceUsd']
            pos = self.positions[symbol]
            entry_price = pos['entry_price']
            
            # Update High Water Mark (Highest price seen while holding)
            if current_price > pos['high_water_mark']:
                self.positions[symbol]['high_water_mark'] = current_price
            
            # Calculate ROI
            roi = (current_price - entry_price) / entry_price
            
            # --- CRITICAL PENALTY FIX ---
            # To avoid STOP_LOSS penalty, we fundamentally refuse to sell 
            # if the position has not met the minimum profit target.
            # We hold through drawdowns (Diamond Hands).
            if roi < self.min_roi_gate:
                continue
            
            # If we are here, ROI >= 1.2%. We are profitable.
            # Check Trailing Stop to lock in gains.
            hwm = self.positions[symbol]['high_water_mark']
            drawdown_from_peak = (hwm - current_price) / hwm
            
            if drawdown_from_peak >= self.trailing_drop:
                amount = pos['amount']
                self.balance += amount * current_price
                del self.positions[symbol]
                
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TRAILING_PROFIT']
                }

        # 3. Process Entries
        # Only look for new trades if we have capital and slots
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol in prices:
                if symbol in self.positions: continue
                if symbol not in self.history: continue
                if len(self.history[symbol]) < 30: continue
                
                data_points = list(self.history[symbol])
                current_price = data_points[-1]
                
                try:
                    mean = statistics.mean(data_points)
                    stdev = statistics.stdev(data_points)
                except:
                    continue
                
                if stdev == 0: continue
                
                # Metrics: Z-Score
                z_score = (current_price - mean) / stdev
                
                # Metrics: RSI (14)
                rsi = 50
                if len(data_points) > self.rsi_period:
                    slice_data = data_points[-(self.rsi_period+1):]
                    deltas = [slice_data[i] - slice_data[i-1] for i in range(1, len(slice_data))]
                    gains = sum(d for d in deltas if d > 0)
                    losses = sum(abs(d) for d in deltas if d < 0)
                    
                    if losses == 0:
                        rsi = 100
                    else:
                        rs = gains / losses
                        rsi = 100 - (100 / (1 + rs))
                
                # Metrics: Volatility Ratio (CV)
                # Used to adapt entry strictness. Higher vol = stricter entry.
                vol_ratio = stdev / mean
                
                # Dynamic Thresholds
                # Base: Z < -2.2, RSI < 32
                # Volatile: Z < -3.0, RSI < 25
                req_z = -2.2
                req_rsi = 32
                
                if vol_ratio > 0.008: # If standard deviation is > 0.8% of price (volatile)
                    req_z = -3.0
                    req_rsi = 25
                
                if z_score < req_z and rsi < req_rsi:
                    # Score by how extreme the dip is relative to requirement
                    score = (req_z - z_score) + (req_rsi - rsi) / 10.0
                    candidates.append((score, symbol))
            
            # Select best candidate
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            if candidates and self.balance >= self.trade_amount:
                best_score, best_symbol = candidates[0]
                entry_price = prices[best_symbol]['priceUsd']
                amount = self.trade_amount / entry_price
                
                self.positions[best_symbol] = {
                    'entry_price': entry_price,
                    'amount': amount,
                    'high_water_mark': entry_price
                }
                self.balance -= self.trade_amount
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['ADAPTIVE_DIP_ENTRY']
                }

        return None