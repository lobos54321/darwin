import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA: Momentum Breakout ===
        # Penalized for MEAN_REVERSION, so we strictly follow trends.
        # We buy strength (Breakouts) and sell weakness (Trend Reversal).
        
        # Randomized parameters for genetic diversity
        self.ema_fast = random.randint(10, 15)
        self.ema_slow = random.randint(30, 40)
        self.rsi_period = 14
        self.breakout_window = random.randint(10, 20)
        
        # Risk Management
        self.max_positions = 5
        self.min_liquidity = 500000.0
        
        # State
        self.history = {}       # symbol -> deque of prices
        self.positions = {}     # symbol -> {'entry': float, 'high_water_mark': float}

    def _calculate_ema(self, data, window):
        """Calculates Exponential Moving Average."""
        if len(data) < window:
            return None
        
        alpha = 2 / (window + 1)
        # Use a simple SMA of the first chunk to seed EMA for stability
        ema = sum(list(data)[:window]) / window
        
        # Iterate through the rest
        for price in list(data)[window:]:
            ema = (price * alpha) + (ema * (1 - alpha))
        return ema

    def _calculate_rsi(self, data, window=14):
        """Calculates Relative Strength Index."""
        if len(data) < window + 1:
            return 50.0
        
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [max(0, c) for c in changes]
        losses = [max(0, -c) for c in changes]
        
        # Simple average for the first window
        avg_gain = sum(gains[-window:]) / window
        avg_loss = sum(losses[-window:]) / window
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _get_volatility(self, data, window=20):
        """Calculates standard deviation of price."""
        if len(data) < window:
            return 0.0
        subset = list(data)[-window:]
        if not subset:
            return 0.0
        return statistics.stdev(subset)

    def on_price_update(self, prices):
        """
        Executed on every price update batch.
        Logic: 
        1. Parse Data & Maintain History.
        2. Check Exits (Trailing Stop or Trend Reversal).
        3. Check Entries (Momentum Breakout).
        """
        
        candidates = []
        active_symbols = list(self.positions.keys())
        
        # 1. Ingestion & Pre-calculation
        for sym, p_data in prices.items():
            # Data Parsing
            try:
                if not p_data or 'priceUsd' not in p_data:
                    continue
                price = float(p_data['priceUsd'])
                liquidity = float(p_data.get('liquidity', 0))
            except (ValueError, TypeError):
                continue

            # History Maintenance
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.ema_slow + 50)
            self.history[sym].append(price)
            
            # Update High Water Mark for active positions (Trailing Stop logic)
            if sym in self.positions:
                self.positions[sym]['high_water_mark'] = max(
                    self.positions[sym]['high_water_mark'], price
                )
            elif liquidity >= self.min_liquidity:
                # Potential candidate if not currently held
                candidates.append(sym)

        # 2. Exit Logic (Priority: Protect Capital)
        for sym in active_symbols:
            hist = self.history[sym]
            if len(hist) < self.ema_slow:
                continue
                
            current_price = hist[-1]
            pos = self.positions[sym]
            
            fast = self._calculate_ema(hist, self.ema_fast)
            slow = self._calculate_ema(hist, self.ema_slow)
            vol = self._get_volatility(hist)
            
            if fast is None or slow is None:
                continue

            # A. Trend Reversal (EMA Cross Down)
            # If fast EMA drops below slow EMA, the uptrend is broken. Sell.
            if fast < slow:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TREND_REVERSAL']}

            # B. Volatility-Based Trailing Stop
            # Protect profits. If price drops 3 std devs from the high water mark, exit.
            stop_distance = max(vol * 3.0, current_price * 0.02) # Minimum 2% buffer
            stop_price = pos['high_water_mark'] - stop_distance
            
            if current_price < stop_price:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TRAILING_STOP']}

        # 3. Entry Logic (Momentum Breakout)
        if len(self.positions) >= self.max_positions:
            return None
            
        # Shuffle candidates to minimize order collision/homogenization
        random.shuffle(candidates)
        
        for sym in candidates:
            hist = self.history[sym]
            if len(hist) < self.ema_slow + 5:
                continue
            
            current_price = hist[-1]
            
            # Indicators
            fast = self._calculate_ema(hist, self.ema_fast)
            slow = self._calculate_ema(hist, self.ema_slow)
            rsi = self._calculate_rsi(hist, self.rsi_period)
            
            if fast is None or slow is None:
                continue
            
            # === Entry Conditions ===
            
            # 1. Trend Filter: Must be in Uptrend
            if fast <= slow:
                continue
                
            # 2. Momentum Filter: Strong RSI (Avoid Mean Reversion)
            # We want RSI > 55 indicating buyers are aggressive.
            # But avoid extreme overheating (> 85).
            if rsi < 55 or rsi > 85:
                continue
                
            # 3. Breakout Filter: Price > Recent Highs
            # Look at the previous N candles (excluding current)
            recent_window = list(hist)[-(self.breakout_window + 1):-1]
            if not recent_window:
                continue
            local_high = max(recent_window)
            
            if current_price > local_high:
                # Confirm breakout strength (Price slightly above EMA)
                if current_price > fast:
                    self.positions[sym] = {
                        'entry': current_price,
                        'high_water_mark': current_price
                    }
                    return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['MOMENTUM_BREAKOUT']}

        return None