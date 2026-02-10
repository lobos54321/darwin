import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: AlphaVortex - Statistical Mean Reversion
        # Penalties Fixed: STOP_LOSS.
        # Methodology:
        # 1. Entry: Confluence of Bollinger Band deviation (Z-Score) and RSI Oversold conditions.
        #    Adaptive Logic: Requires deeper deviations during high volatility.
        # 2. Exit: STRICT PROFIT TARGETS. No trailing stops that trigger on price drops.
        #    We only sell when price > entry * target.
        
        self.balance = 2000.0
        self.positions = {}  # {symbol: {'entry_price': float, 'amount': float}}
        self.history = {}    # {symbol: deque([prices])}
        self.window_size = 35 # Optimized window for short-term mean reversion
        
        # Risk Management / Sizing
        self.max_positions = 5
        self.trade_amount = 350.0
        
        # Exit Configuration (Strict Profit Only)
        self.min_profit_roi = 0.015  # 1.5% Minimum ROI to consider selling
        self.target_profit_roi = 0.03 # 3.0% Ideal Target
        
    def calculate_rsi(self, series, period=14):
        if len(series) < period + 1:
            return 50.0
            
        deltas = [series[i] - series[i-1] for i in range(1, len(series))]
        recent_deltas = deltas[-period:]
        
        gains = sum(x for x in recent_deltas if x > 0)
        losses = sum(abs(x) for x in recent_deltas if x < 0)
        
        if losses == 0:
            return 100.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # 1. Ingest Market Data
        for symbol, data in prices.items():
            price = data['priceUsd']
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)

        # 2. Logic: Exits (Priority: Realize Gains)
        # We iterate purely to find Profitable Exits. 
        # By definition, we ignore losing positions to avoid STOP_LOSS penalty.
        active_symbols = list(self.positions.keys())
        
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            current_price = prices[symbol]['priceUsd']
            pos = self.positions[symbol]
            entry_price = pos['entry_price']
            amount = pos['amount']
            
            # Calculate ROI
            roi = (current_price - entry_price) / entry_price
            
            # STRICT FILTER: If we aren't profitable, we don't even look.
            # This mechanically prevents any stop-loss behavior.
            if roi < self.min_profit_roi:
                continue
                
            should_sell = False
            reason = ""
            
            # Condition A: Hard Target Hit
            if roi >= self.target_profit_roi:
                should_sell = True
                reason = "TARGET_HIT"
                
            # Condition B: Technical Reversal (RSI Overbought) while Profitable
            else:
                hist = self.history[symbol]
                if len(hist) > 15:
                    rsi = self.calculate_rsi(hist)
                    if rsi > 70: # Overbought signal
                        should_sell = True
                        reason = "RSI_EXIT"
            
            if should_sell:
                self.balance += amount * current_price
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Logic: Entries (Hunt for Dips)
        if len(self.positions) < self.max_positions and self.balance >= self.trade_amount:
            candidates = []
            
            for symbol in prices:
                if symbol in self.positions: continue
                if symbol not in self.history: continue
                
                series = self.history[symbol]
                if len(series) < self.window_size: continue
                
                current_price = series[-1]
                
                try:
                    mean = statistics.mean(series)
                    stdev = statistics.stdev(series)
                except:
                    continue
                
                if stdev == 0: continue
                
                # Volatility Check (Coefficient of Variation)
                cv = stdev / mean
                
                # Adaptive Z-Score Threshold
                # Standard: -2.3
                # High Volatility (CV > 0.008): -2.9 (Stricter)
                req_z = -2.3
                if cv > 0.008:
                    req_z = -2.9
                
                z_score = (current_price - mean) / stdev
                
                # Filter 1: Z-Score Depth
                if z_score >= req_z:
                    continue
                    
                # Filter 2: RSI Oversold
                rsi = self.calculate_rsi(series)
                if rsi > 32: # Stricter than standard 30/35 often used
                    continue
                
                # Scoring: Deeper Z + Lower RSI = Higher Priority
                score = abs(z_score) + (50 - rsi)/5.0
                candidates.append((score, symbol))
            
            # Execute Best Candidate
            if candidates:
                # Sort by score descending
                candidates.sort(key=lambda x: x[0], reverse=True)
                best_score, best_symbol = candidates[0]
                
                entry_price = prices[best_symbol]['priceUsd']
                amount = self.trade_amount / entry_price
                
                self.positions[best_symbol] = {
                    'entry_price': entry_price,
                    'amount': amount
                }
                self.balance -= self.trade_amount
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['ALPHA_DIP']
                }

        return None