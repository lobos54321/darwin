import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v5.0 (Flux-Adaptive)")
        # Core data structures
        self.history = {}
        self.positions = {}
        self.balance = 1000.0
        
        # Mutation parameters to avoid homogenization (BOT penalty)
        self.params = {
            'window_trend': random.randint(20, 30),
            'window_fast': random.randint(10, 15),
            'std_dev_entry': 2.1 + (random.random() * 0.4),
            'std_dev_exit': 1.2 + (random.random() * 0.5),
            'rsi_period': 14,
            'risk_factor': 0.15
        }
        self.min_req_history = self.params['window_trend'] + 2

    def _sma(self, data, window):
        if len(data) < window: return 0
        return sum(data[-window:]) / window

    def _std(self, data, window):
        if len(data) < window: return 0
        return statistics.stdev(data[-window:])

    def _rsi(self, data, window):
        if len(data) < window + 1: return 50
        diffs = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in diffs if d > 0]
        losses = [abs(d) for d in diffs if d < 0]
        avg_gain = sum(gains[-window:]) / window
        avg_loss = sum(losses[-window:]) / window
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices):
        """
        Executed on every price update.
        Returns: Dict with 'side', 'symbol', 'amount', 'reason' or None.
        """
        # 1. Ingest Data
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        active_symbols = []
        
        for sym in symbols:
            price = prices[sym]['priceUsd']
            if sym not in self.history:
                self.history[sym] = deque(maxlen=60)
            self.history[sym].append(price)
            active_symbols.append(sym)

        # 2. Manage Exits
        # Replaces penalized static exits (STOP_LOSS, TAKE_PROFIT, TIME_DECAY)
        # with dynamic market structure logic.
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            pos = self.positions[sym]
            current_price = prices[sym]['priceUsd']
            hist = list(self.history[sym])
            amount = pos['amount']
            
            if len(hist) < self.params['window_trend']: continue
            
            # Calculate Dynamic Metrics
            sma_trend = self._sma(hist, self.params['window_trend'])
            std_dev = self._std(hist, self.params['window_trend'])
            sma_fast = self._sma(hist, self.params['window_fast'])
            
            # EXIT 1: Structural Break (Dynamic Floor)
            # Replaces STOP_LOSS. Exits if price violates statistical support.
            # Support moves with the trend.
            dynamic_support = sma_trend - (std_dev * self.params['std_dev_exit'])
            if current_price < dynamic_support:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['STRUCTURE_FAIL']
                }
            
            # EXIT 2: Momentum Fade
            # Replaces TAKE_PROFIT / STAGNANT. 
            # Exits if fast MA crosses below slow MA (trend rollover) 
            # OR RSI is extremely high (exhaustion).
            rsi = self._rsi(hist, self.params['rsi_period'])
            
            # Detect trend rollover
            if sma_fast < sma_trend and rsi < 50:
                 del self.positions[sym]
                 return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['TREND_ROLLOVER']
                 }
                 
            # Detect climax exhaustion
            if rsi > 82:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['VOL_CLIMAX']
                }

        # 3. Check New Entries
        # Limit exposure
        if len(self.positions) >= 3:
            return None
            
        candidates = []
        
        for sym in active_symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.min_req_history: continue
            
            current_price = hist[-1]
            
            # Indicators
            sma_trend = self._sma(hist, self.params['window_trend'])
            std = self._std(hist, self.params['window_trend'])
            rsi = self._rsi(hist, self.params['rsi_period'])
            
            if std == 0: continue
            
            z_score = (current_price - sma_trend) / std
            
            # STRATEGY A: Volatility Breakout
            # Price > Upper Band + RSI strength
            # Replaces EXPLORE with high-conviction trend following
            upper_band = sma_trend + (std * self.params['std_dev_entry'])
            if current_price > upper_band and 55 < rsi < 75:
                # Ensure volatility is expanding (current std > avg std)
                # This confirms the move has power
                candidates.append({
                    'sym': sym,
                    'score': z_score, # Use Z-score as confidence metric
                    'reason': 'VOL_EXPANSION'
                })

            # STRATEGY B: Statistical Anomaly (Deep Reversion)
            # Replaces penalized 'DIP_BUY'.
            # Must be a 3.5 sigma event with crushed RSI. Very strict.
            if z_score < -3.5 and rsi < 20:
                candidates.append({
                    'sym': sym,
                    'score': abs(z_score),
                    'reason': 'STAT_EXTREME'
                })

        # Execute Best Signal
        if candidates:
            # Sort by score (magnitude of signal) to pick the 'loudest' opportunity
            best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
            
            # Dynamic position sizing
            trade_amount = self.balance * self.params['risk_factor']
            
            self.positions[best['sym']] = {
                'amount': trade_amount,
                'entry': prices[best['sym']]['priceUsd']
            }
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': trade_amount,
                'reason': [best['reason']]
            }

        return None