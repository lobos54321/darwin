import statistics
import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        # Configuration - Hyper-Strict Parameters to mitigate 'DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE'
        self.history_size = 200  # Increased to 200 for deep macro trend context
        self.rsi_period = 14
        self.bb_window = 20
        self.bb_std = 3.5        # Increased to 3.5 (Requires ~0.02% probability event)
        self.ema_period = 200    # Increased to 200 (Stricter trend requirement)
        self.rsi_limit = 12      # Decreased to 12 (Filters out standard oversold noise)
        
        # Risk Management
        self.max_positions = 1
        self.trade_amount = 0.1
        self.atr_stop_mult = 1.2 # Tight trailing stop
        
        # Data State
        self.prices = defaultdict(lambda: deque(maxlen=self.history_size))
        self.positions = {} # {symbol: {'entry': float, 'highest': float, 'atr': float}}

    def _calculate_indicators(self, symbol):
        data = list(self.prices[symbol])
        if len(data) < self.history_size:
            return None
            
        current_price = data[-1]
        prev_price = data[-2]
        
        # 1. EMA 200 (Macro Trend Filter)
        k = 2 / (self.ema_period + 1)
        ema = data[0]
        for p in data[1:]:
            ema = (p * k) + (ema * (1 - k))
            
        # 2. Bollinger Bands (3.5 Sigma)
        bb_slice = data[-self.bb_window:]
        sma_20 = statistics.mean(bb_slice)
        std_dev = statistics.stdev(bb_slice)
        
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
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        # 4. ATR (Volatility)
        tr_sum = 0
        for i in range(1, 15):
            high = max(data[-i], data[-i-1])
            low = min(data[-i], data[-i-1])
            tr_sum += (high - low)
        atr = tr_sum / 14
        
        # Z-Score
        z_score = (current_price - sma_20) / std_dev if std_dev > 0 else 0
        
        return {
            'sma_20': sma_20,
            'rsi': rsi,
            'ema': ema,
            'atr': atr,
            'z_score': z_score,
            'prev_price': prev_price
        }

    def on_price_update(self, prices):
        """
        Executed on every price update.
        """
        # 1. Update Market Data
        for symbol, price in prices.items():
            self.prices[symbol].append(price)

        # 2. Check Exits (Priority: Protect Capital)
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = prices[symbol]
            
            # Update trailing high
            if current_price > pos['highest']:
                self.positions[symbol]['highest'] = current_price
                
            inds = self._calculate_indicators(symbol)
            if not inds: continue
            
            # Exit A: Tight Trailing Stop
            stop_price = pos['highest'] - (pos['atr'] * self.atr_stop_mult)
            if current_price < stop_price:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['STOP_LOSS_TRAIL']
                }
            
            # Exit B: Mean Reversion Target
            if current_price >= inds['sma_20']:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['TP_MEAN_REVERT']
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
            
            # --- PENALTY FIXES & LOGIC REWRITE ---
            
            # Fix 1: Trend Filter (Avoid 'DIP_BUY' in bear markets)
            if price <= inds['ema']:
                continue

            # Fix 2: Falling Knife Protection (Fix 'DIP_BUY')
            # Condition: Price must be ticking UP. We never buy a red candle.
            # This proves the bottom *might* be in, rather than guessing.
            if price <= inds['prev_price']:
                continue
                
            # Fix 3: Extreme Statistical Dislocation (Fix 'OVERSOLD')
            # Require Z-Score < -3.5 (Statistical anomaly, not just oversold)
            if inds['z_score'] > -self.bb_std:
                continue
            
            # Fix 4: RSI Extremity (Fix 'RSI_CONFLUENCE')
            # Require RSI < 12 (Deep panic only)
            if inds['rsi'] > self.rsi_limit:
                continue
                
            # Score by volatility-adjusted depth
            score = abs(inds['z_score'])
            
            if score > best_score:
                best_score = score
                best_order = symbol

        if best_order:
            symbol = best_order
            inds = self._calculate_indicators(symbol)
            
            self.positions[symbol] = {
                'entry': prices[symbol],
                'highest': prices[symbol],
                'atr': inds['atr']
            }
            
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': self.trade_amount,
                'reason': ['ANOMALY_REVERSAL_CONFIRMED']
            }

        return None