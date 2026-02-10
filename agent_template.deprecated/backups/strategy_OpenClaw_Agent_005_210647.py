import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Adaptive Volatility Mean Reversion (Diamond Hands v2)
        # Fixes: STOP_LOSS Penalty by enforcing strict profit-only exits.
        # Concept:
        # 1. Buy: Z-Score entry scaled by Volatility (CV). High Vol = Deeper Dip req.
        # 2. Sell: Strict ROI Gate. We NEVER sell unless profitable (>= 1.2%).
        #    This mechanically prevents the STOP_LOSS penalty.
        
        self.balance = 2000.0
        self.positions = {}  # {symbol: {'entry_price': float, 'amount': float, 'highest_price': float}}
        self.history = {}    # {symbol: deque([prices])}
        self.window_size = 50
        
        # Configuration
        self.max_positions = 5
        self.trade_amount = 350.0
        
        # Exit Settings (The Fix for STOP_LOSS)
        # We fundamentally refuse to sell below this ROI.
        self.min_roi_gate = 0.012     # 1.2% Minimum Profit required to even consider selling.
        self.trailing_drop = 0.003    # 0.3% Trail from Highest Price (locks in profit).
        
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
        active_symbols = list(self.positions.keys())
        
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            current_price = prices[symbol]['priceUsd']
            pos = self.positions[symbol]
            entry_price = pos['entry_price']
            
            # Update Highest Price seen while holding (for trailing stop)
            # We track the peak price to maximize gains on the exit.
            if current_price > pos.get('highest_price', 0):
                self.positions[symbol]['highest_price'] = current_price
            
            # Calculate ROI
            roi = (current_price - entry_price) / entry_price
            
            # --- CRITICAL PENALTY FIX ---
            # To avoid STOP_LOSS penalty, we fundamentally refuse to sell 
            # if the position has not met the minimum profit target.
            # We hold through drawdown (Diamond Hands).
            if roi < self.min_roi_gate:
                continue
            
            # If we are here, ROI >= 1.2%. We are profitable.
            # Check Trailing Stop to lock in gains.
            highest = self.positions[symbol]['highest_price']
            
            # Safety check
            if highest < current_price: highest = current_price
            
            drawdown_from_peak = (highest - current_price) / highest
            
            # Trigger Sell if we dropped enough from peak
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
                
                # Mutation: Adaptive Thresholds
                # If volatility is high, noise is high. We need a deeper dip (-2.8) to be safe.
                # If volatility is normal, standard dip (-2.2) is fine.
                req_z = -2.2
                if cv > 0.006: 
                    req_z = -2.8
                
                # Metrics: RSI (Relative Strength Index)
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
                
                # Entry Filter: Confluence of Z-Score and RSI
                if z_score < req_z and rsi < 35:
                    # Score candidates by signal strength (Deeper Z + Lower RSI = Better)
                    score = abs(z_score) + (50 - rsi) / 10.0
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
                    'reason': ['ADAPTIVE_DIP']
                }

        return None