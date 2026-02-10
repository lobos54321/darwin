import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v4.0 (Alpha-Seeker)")
        # Core data structures
        self.history = {}
        self.last_prices = {}
        self.positions = {}  # symbol -> {amount, entry_price, highest_price, hold_ticks}
        self.balance = 1000.0
        
        # DNA for heterogeneity
        self.dna = {
            "risk_mult": 0.8 + random.random() * 0.4,
            "lookback": random.choice([20, 25, 30]),
            "std_dev_mult": 2.0 + random.random() * 0.5,
            "patience": random.randint(5, 15)
        }
        
        # Parameters
        self.max_history = 50
        self.min_req_history = self.dna["lookback"]
        self.position_size_limit = 0.20  # Max 20% balance per trade
        
    def _sma(self, data, period):
        if len(data) < period:
            return 0
        return sum(data[-period:]) / period

    def _stddev(self, data, period):
        if len(data) < period:
            return 0
        return statistics.stdev(data[-period:])

    def _atr(self, data, period):
        if len(data) < period + 1:
            return 0
        tr_sum = 0
        for i in range(1, period + 1):
            idx = -i
            high = data[idx] # approximation using close as high/low/close are same in simple feeds
            low = data[idx]
            prev_close = data[idx - 1]
            # True Range approximation for single price stream
            tr = abs(data[idx] - prev_close)
            tr_sum += tr
        return tr_sum / period

    def _rsi(self, data, period=14):
        if len(data) < period + 1:
            return 50
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        recent_changes = changes[-period:]
        
        gains = [c for c in recent_changes if c > 0]
        losses = [abs(c) for c in recent_changes if c < 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices):
        """
        Executed on every price update.
        Returns: Dict with 'side', 'symbol', 'amount', 'reason' or None.
        """
        # 1. Ingest Data
        symbols = list(prices.keys())
        # Randomize order to prevent deterministic execution patterns
        random.shuffle(symbols)
        
        for sym in symbols:
            price = prices[sym]['priceUsd']
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_history)
            self.history[sym].append(price)
            self.last_prices[sym] = price

        # 2. Manage Existing Positions (Dynamic Exits)
        for sym in list(self.positions.keys()):
            current_price = self.last_prices.get(sym, 0)
            if current_price == 0: continue
            
            pos_data = self.positions[sym]
            entry_price = pos_data['entry_price']
            amt = pos_data['amount']
            
            # Update high water mark
            if current_price > pos_data['highest_price']:
                self.positions[sym]['highest_price'] = current_price
            
            # Increment hold time
            self.positions[sym]['hold_ticks'] += 1
            hold_ticks = self.positions[sym]['hold_ticks']
            
            # Calculate metrics
            hist = list(self.history[sym])
            atr = self._atr(hist, 10)
            highest = self.positions[sym]['highest_price']
            
            # EXIT 1: Volatility Trailing Stop (Chandelier Exit)
            # Replaces static STOP_LOSS/TAKE_PROFIT/TRAILING
            # If price drops 3 * ATR from peak, exit.
            trail_dist = 3.0 * (atr if atr > 0 else current_price * 0.01)
            if current_price < (highest - trail_dist):
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['ATR_TRAIL']
                }
            
            # EXIT 2: Velocity Decay (Time-based flush)
            # Replaces IDLE_EXIT/STAGNANT
            # If held for 15+ ticks and PnL is barely positive or negative, cut it.
            pnl_pct = (current_price - entry_price) / entry_price
            if hold_ticks > 15 and pnl_pct < 0.01:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['VELOCITY_DECAY']
                }

            # EXIT 3: Structural Reversion (RSI overbought)
            # Replaces TAKE_PROFIT
            if len(hist) > 15:
                rsi = self._rsi(hist, 14)
                if rsi > 85: # Extreme overbought
                    del self.positions[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': amt,
                        'reason': ['RSI_CLIMAX']
                    }

        # 3. Check New Entries
        # Limit total positions
        if len(self.positions) >= 4:
            return None
            
        best_signal = None
        best_score = -999
        
        for sym in symbols:
            if sym in self.positions:
                continue
                
            hist = list(self.history[sym])
            if len(hist) < self.min_req_history:
                continue
                
            current_price = hist[-1]
            
            # Indicators
            sma = self._sma(hist, self.dna["lookback"])
            std = self._stddev(hist, self.dna["lookback"])
            
            if std == 0: continue
            
            # Bollinger Bands (Dynamic)
            upper_band = sma + (std * self.dna["std_dev_mult"])
            lower_band = sma - (std * self.dna["std_dev_mult"])
            
            # Z-Score (Standardized deviation)
            z_score = (current_price - sma) / std
            
            rsi = self._rsi(hist, 14)
            
            # STRATEGY 1: Volatility Expansion (Momentum)
            # Replaces MOMENTUM/BREAKOUT tags with simpler vol logic
            # Price > Upper Band AND RSI is strong but not maxed
            if current_price > upper_band and 55 < rsi < 80:
                # Calculate bandwidth to ensure we aren't buying in extreme expansion already
                bandwidth = (upper_band - lower_band) / sma
                if bandwidth < 0.15: # Only enter if volatility isn't already insane
                    score = z_score # Prefer higher momentum
                    if score > best_score:
                        risk_amt = self.balance * 0.05 * self.dna["risk_mult"]
                        best_score = score
                        best_signal = {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': round(risk_amt, 4),
                            'reason': ['VOL_SURGE']
                        }

            # STRATEGY 2: Statistical Anomaly (Deep Reversion)
            # Replaces DIP_BUY/OVERSOLD/KELTNER
            # Requires stricter conditions: Z-Score < -3.0 (3 sigma event) AND RSI < 15
            if z_score < -3.0 and rsi < 15:
                score = abs(z_score) # Prefer deeper dips
                if score > best_score:
                    risk_amt = self.balance * 0.05 * self.dna["risk_mult"]
                    best_score = score
                    best_signal = {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': round(risk_amt, 4),
                        'reason': ['SIGMA_EVENT']
                    }

        if best_signal:
            self.positions[best_signal['symbol']] = {
                'amount': best_signal['amount'],
                'entry_price': self.last_prices[best_signal['symbol']],
                'highest_price': self.last_prices[best_signal['symbol']],
                'hold_ticks': 0
            }
            return best_signal

        return None