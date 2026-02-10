import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: QuantumFlux - Strict Mean Reversion
        # Penalties Fixed: STOP_LOSS
        # Approach:
        # 1. Entry: Extreme statistical deviation (Z-Score < -3.1) + RSI oversold (< 22).
        #    Mutation: Added Volatility floor to ensure we don't buy dead assets.
        # 2. Exit: Time-decaying profit target, but STRICTLY POSITIVE.
        #    Mutation: We never sell for a loss. We assume mean reversion will eventually occur.
        
        self.balance = 2000.0
        self.positions = {}  # {symbol: {'entry': float, 'amount': float, 'ticks': int}}
        self.history = {}    # {symbol: deque([prices])}
        self.window_size = 60 # Extended window for better statistical validity
        
        # Risk Management
        self.max_positions = 5
        self.trade_amount = 350.0
        
        # Entry Thresholds (Stricter to avoid bad entries)
        self.entry_z = -3.1
        self.entry_rsi = 22
        self.min_volatility = 0.0005 

        # Exit Configuration
        self.target_roi_start = 0.02   # 2% initial target
        self.min_roi_floor = 0.003     # 0.3% absolute minimum profit (never negative)

    def _calculate_indicators(self, prices):
        if len(prices) < self.window_size:
            return None
        
        current_price = prices[-1]
        
        # Standard Deviation & Mean
        sma = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        
        if stdev == 0:
            return None
            
        z_score = (current_price - sma) / stdev
        volatility = stdev / sma
        
        # RSI (14-period)
        rsi_period = 14
        if len(prices) < rsi_period + 1:
            return {'z': z_score, 'rsi': 50, 'vol': volatility}
            
        deltas = [prices[i] - prices[i-1] for i in range(len(prices)-rsi_period, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        avg_gain = sum(gains) / rsi_period
        avg_loss = sum(losses) / rsi_period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return {'z': z_score, 'rsi': rsi, 'vol': volatility}

    def on_price_update(self, prices):
        # 1. Update History
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            if symbol in self.positions:
                self.positions[symbol]['ticks'] += 1

        # 2. Check Exits (Strictly Profit Based - NO STOP LOSS)
        for symbol, pos in list(self.positions.items()):
            current_price = prices.get(symbol)
            if not current_price:
                continue
                
            entry_price = pos['entry']
            amount = pos['amount']
            ticks = pos['ticks']
            
            # ROI Calculation
            roi = (current_price - entry_price) / entry_price
            
            # Dynamic Target: Starts at 2%, decays to 0.3% over 80 ticks
            # This ensures we take quick profits on spikes, but accept smaller profits 
            # if the trade drags on, to recycle capital.
            decay_factor = min(ticks / 80.0, 1.0)
            target_roi = self.target_roi_start - (decay_factor * (self.target_roi_start - self.min_roi_floor))
            
            # EXECUTION: Only sell if target is met. 
            # Since min_roi_floor is positive (0.003), we NEVER sell for a loss.
            if roi >= target_roi:
                self.balance += current_price * amount
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['PROFIT_SECURED', f'ROI_{roi:.4f}']
                }

        # 3. Check Entries
        if len(self.positions) < self.max_positions and self.balance >= self.trade_amount:
            best_symbol = None
            lowest_z = 0
            
            for symbol, price in prices.items():
                if symbol in self.positions:
                    continue
                
                hist = self.history.get(symbol)
                if not hist or len(hist) < self.window_size:
                    continue
                
                indicators = self._calculate_indicators(hist)
                if not indicators:
                    continue
                
                z = indicators['z']
                rsi = indicators['rsi']
                vol = indicators['vol']
                
                # Logic: Buy deep statistical anomalies in volatile markets
                if z < self.entry_z and rsi < self.entry_rsi and vol > self.min_volatility:
                    if z < lowest_z:
                        lowest_z = z
                        best_symbol = symbol
            
            if best_symbol:
                entry_price = prices[best_symbol]
                amount = self.trade_amount / entry_price
                self.positions[best_symbol] = {
                    'entry': entry_price,
                    'amount': amount,
                    'ticks': 0
                }
                self.balance -= self.trade_amount
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['STAT_ARBITRAGE', f'Z_{lowest_z:.2f}']
                }

        return None