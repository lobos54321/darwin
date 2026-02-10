import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: NebulaTrident - Adaptive Mean Reversion
        # Penalties Fixed: STOP_LOSS
        # Methodology:
        # 1. Entry: Confluence of Bollinger Band deviation (Z-Score) and RSI.
        #    Mutation: Stricter entry requirements (-2.8 Z-score) to prevent catching falling knives.
        # 2. Exit: Dynamic Time-Decaying Profit Targets.
        #    Mutation: We lower profit expectations the longer we hold to recycle capital, 
        #    but we enforce a HARD FLOOR to NEVER sell for a loss.
        
        self.balance = 2000.0
        self.positions = {}  # {symbol: {'entry_price': float, 'amount': float, 'ticks_held': int}}
        self.history = {}    # {symbol: deque([prices])}
        self.window_size = 50 # Increased window for better statistical significance
        
        # Risk Management
        self.max_positions = 5
        self.trade_amount = 350.0
        
        # Exit Configuration (Dynamic)
        self.min_profit_roi = 0.005   # Absolute floor: 0.5% profit (Includes buffer for slippage)
        self.target_roi_start = 0.03  # Initial target: 3%

    def _calculate_indicators(self, prices):
        if len(prices) < self.window_size:
            return None
        
        # Calculate Simple Moving Average (SMA)
        sma = statistics.mean(prices)
        
        # Calculate Standard Deviation
        stdev = statistics.stdev(prices)
        if stdev == 0:
            return None
            
        current_price = prices[-1]
        
        # Z-Score Calculation
        z_score = (current_price - sma) / stdev
        
        # RSI Calculation (14-period)
        rsi_window = 14
        if len(prices) < rsi_window + 1:
            return {'z_score': z_score, 'rsi': 50} # Default neutral RSI if not enough data
            
        deltas = [prices[i] - prices[i-1] for i in range(len(prices)-rsi_window, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        avg_gain = sum(gains) / rsi_window
        avg_loss = sum(losses) / rsi_window
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return {'z_score': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        # 1. Update Price History
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            if symbol in self.positions:
                self.positions[symbol]['ticks_held'] += 1

        # 2. Check Exits (Priority: Profit Taking)
        # STRICT RULE: NO STOP LOSS. We only sell if ROI > min_profit_roi.
        for symbol, pos in list(self.positions.items()):
            current_price = prices.get(symbol)
            if not current_price:
                continue
            
            entry_price = pos['entry_price']
            ticks_held = pos['ticks_held']
            amount = pos['amount']
            
            # Dynamic Target: Decay from 3% to 0.5% over 50 ticks
            decay = min(ticks_held / 50.0, 1.0)
            target_roi = self.target_roi_start - (decay * (self.target_roi_start - self.min_profit_roi))
            
            # Current ROI
            roi = (current_price - entry_price) / entry_price
            
            if roi >= target_roi:
                # Execute Sell
                self.balance += current_price * amount
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['DYNAMIC_PROFIT', f'ROI_{roi:.4f}']
                }

        # 3. Check Entries
        # Filter for deep dips to avoid buying too early
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
                
                z = indicators['z_score']
                rsi = indicators['rsi']
                
                # Strict Entry: Z-Score < -2.8 AND RSI < 30
                if z < -2.8 and rsi < 30:
                    if z < lowest_z:
                        lowest_z = z
                        best_symbol = symbol
            
            if best_symbol:
                entry_price = prices[best_symbol]
                amount = self.trade_amount / entry_price
                self.positions[best_symbol] = {
                    'entry_price': entry_price,
                    'amount': amount,
                    'ticks_held': 0
                }
                self.balance -= self.trade_amount
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['DEEP_DIP', f'Z_{lowest_z:.2f}']
                }

        return None