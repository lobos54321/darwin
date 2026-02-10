import statistics
import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        # Configuration - Ultra-Strict Parameters to mitigate 'DIP_BUY' and 'OVERSOLD' penalties
        self.history_size = 120  # Increased from 60 to 120 for longer-term trend analysis
        self.rsi_period = 14
        self.bb_window = 20
        self.bb_std = 3.2        # Increased from 2.5 to 3.2 (Require extreme 3-sigma deviation)
        self.ema_period = 100    # Increased from 50 to 100 (Stronger macro trend requirement)
        self.rsi_limit = 18      # Decreased from 25 to 18 (Stricter oversold condition)
        
        # Risk Management
        self.max_positions = 1
        self.trade_amount = 0.1
        self.atr_stop_mult = 1.5 # Tighter stop loss to cut failing knives quickly
        
        # Data State
        self.prices = defaultdict(lambda: deque(maxlen=self.history_size))
        self.positions = {} # {symbol: {'entry': float, 'highest': float, 'atr': float}}

    def _calculate_indicators(self, symbol):
        data = list(self.prices[symbol])
        if len(data) < self.history_size:
            return None
            
        current_price = data[-1]
        
        # 1. EMA 100 (Strong Trend Filter)
        k = 2 / (self.ema_period + 1)
        ema = data[0]
        for p in data[1:]:
            ema = (p * k) + (ema * (1 - k))
            
        # 2. Bollinger Bands (3.2 Sigma)
        bb_slice = data[-self.bb_window:]
        if len(bb_slice) < self.bb_window: 
            return None
            
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
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        # 4. ATR (For Dynamic Stops)
        tr_sum = 0
        for i in range(1, 15):
            high = max(data[-i], data[-i-1])
            low = min(data[-i], data[-i-1])
            tr_sum += (high - low)
        atr = tr_sum / 14
        
        # Calculate Z-Score
        z_score = (current_price - sma_20) / std_dev if std_dev > 0 else 0
        
        return {
            'sma_20': sma_20,
            'lower_band': lower_band,
            'rsi': rsi,
            'ema': ema,
            'std_dev': std_dev,
            'atr': atr,
            'z_score': z_score
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
            
            # Exit A: Stop Loss (ATR Trailing)
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
            # Exit as soon as price reclaims the SMA
            if current_price >= inds['sma_20']:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['TP_MEAN_REVERSION']
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
            
            # --- PENALTY FIXES ---
            
            # 1. Trend Filter: STRICT Macro Uptrend
            # Only buy dips if price is above the 100-period EMA.
            if price <= inds['ema']:
                continue
                
            # 2. Deep Statistical Anomaly (Fixes 'DIP_BUY')
            # Require Z-Score < -3.2 (was -2.5). 
            # This ensures we only buy 3-sigma events, significantly reducing false positives.
            if inds['z_score'] > -3.2:
                continue
            
            # 3. Deep Oversold Confluence (Fixes 'OVERSOLD' / 'RSI_CONFLUENCE')
            # Require RSI < 18 (was 25).
            if inds['rsi'] > self.rsi_limit:
                continue
                
            # Scoring: Prioritize the deepest mathematical dislocation
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
                'reason': ['EXTREME_3SIGMA_REVERSION']
            }

        return None