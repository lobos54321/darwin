import statistics
import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        # Configuration - Stricter parameters to address 'DIP_BUY' and 'OVERSOLD' penalties
        self.history_size = 60
        self.rsi_period = 14
        self.bb_window = 20
        self.bb_std = 2.5  # Increased from 2.0 to 2.5 (Require deeper statistical deviation)
        self.ema_period = 50 # Trend filter period
        
        # Risk Management
        self.max_positions = 1 # Limit exposure to focus on highest quality setups
        self.trade_amount = 0.1
        self.atr_stop_mult = 2.0
        
        # Data State
        self.prices = defaultdict(lambda: deque(maxlen=self.history_size))
        self.positions = {} # {symbol: {'entry': float, 'highest': float, 'atr': float}}

    def _calculate_indicators(self, symbol):
        data = list(self.prices[symbol])
        if len(data) < self.history_size:
            return None
            
        current_price = data[-1]
        
        # 1. EMA 50 (Trend Filter)
        k = 2 / (self.ema_period + 1)
        ema_50 = data[0]
        for p in data[1:]:
            ema_50 = (p * k) + (ema_50 * (1 - k))
            
        # 2. Bollinger Bands
        bb_slice = data[-self.bb_window:]
        if len(bb_slice) < 2: return None
        sma_20 = statistics.mean(bb_slice)
        std_dev = statistics.stdev(bb_slice)
        lower_band = sma_20 - (self.bb_std * std_dev)
        
        # 3. RSI
        gains, losses = [], []
        for i in range(len(data) - self.rsi_period, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        rsi = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain/avg_loss)))
        
        # 4. ATR (For Dynamic Stops)
        tr_sum = 0
        for i in range(1, 15):
            high = max(data[-i], data[-i-1])
            low = min(data[-i], data[-i-1])
            tr_sum += (high - low)
        atr = tr_sum / 14
        
        return {
            'sma_20': sma_20,
            'lower_band': lower_band,
            'rsi': rsi,
            'ema_50': ema_50,
            'std_dev': std_dev,
            'atr': atr,
            'z_score': (current_price - sma_20) / std_dev if std_dev > 0 else 0
        }

    def on_price_update(self, prices):
        """
        Executed on every price update.
        Returns a dictionary representing an order, or None.
        """
        # 1. Update Market Data
        for symbol, price in prices.items():
            self.prices[symbol].append(price)

        # 2. Check Exits (Priority: Protect Capital)
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = prices[symbol]
            
            # Track highest price for trailing stop
            if current_price > pos['highest']:
                self.positions[symbol]['highest'] = current_price
                
            inds = self._calculate_indicators(symbol)
            if not inds: continue
            
            # Exit A: Stop Loss (Chandelier Exit)
            stop_price = pos['highest'] - (pos['atr'] * self.atr_stop_mult)
            if current_price < stop_price:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['STOP_LOSS_ATR']
                }
            
            # Exit B: Take Profit (Mean Reversion Complete)
            # If price returns to SMA 20, the anomaly is resolved.
            if current_price >= inds['sma_20']:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['TAKE_PROFIT_MEAN']
                }

        # 3. Check Entries
        if len(self.positions) >= self.max_positions:
            return None

        best_score = -float('inf')
        best_order = None

        for symbol, price in prices.items():
            if symbol in self.positions: continue
            
            inds = self._calculate_indicators(symbol)
            if not inds: continue
            
            # --- STRATEGY FIXES ---
            # 1. Trend Filter: ONLY buy dips if we are in a macro uptrend.
            # This fixes 'DIP_BUY' penalties in bear markets.
            if price <= inds['ema_50']:
                continue
                
            # 2. Stricter Oversold Logic: 
            # Require Z-Score < -2.5 (Statistical Extremes) AND RSI < 25.
            # This fixes 'OVERSOLD' and 'RSI_CONFLUENCE' false positives.
            if inds['z_score'] > -2.5:
                continue
            if inds['rsi'] > 25:
                continue
                
            # Scoring: Prioritize the deepest statistical deviation
            score = abs(inds['z_score']) + (100 - inds['rsi'])
            
            if score > best_score:
                best_score = score
                best_order = symbol

        if best_order:
            symbol = best_order
            inds = self._calculate_indicators(symbol)
            
            # Register Position
            self.positions[symbol] = {
                'entry': prices[symbol],
                'highest': prices[symbol],
                'atr': inds['atr']
            }
            
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': self.trade_amount,
                'reason': ['TREND_MEAN_REVERSION']
            }

        return None