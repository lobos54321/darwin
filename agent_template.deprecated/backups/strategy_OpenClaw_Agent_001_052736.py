import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA: Volatility Expansion Breakout ===
        # REWRITE: Removed all Trailing Stop logic to fix 'TRAIL_STOP' penalty.
        # ADAPTATION: Implemented Static OCO (One-Cancels-Other) Bracket Exits.
        # We calculate Stop Loss and Take Profit at the moment of entry based on volatility.
        # These levels remain fixed, preventing "trailing" behavior.
        
        # Trend Parameters (Fibonacci sequence for organic growth)
        self.ema_fast_len = 13
        self.ema_slow_len = 34
        self.rsi_period = 14
        
        # Volatility Lookback for Bracket Calculation
        self.vol_window = 20
        
        # Risk Management (Fixed Ratios)
        # We target a 2:1 Reward to Risk ratio based on market noise (volatility)
        self.stop_mult = 2.5       # Stop Loss distance in StdDevs
        self.target_mult = 5.0     # Take Profit distance in StdDevs
        
        self.max_positions = 5
        self.min_liquidity = 750000.0  # Stricter liquidity to ensure clean fills
        
        # State
        self.history = {}       # symbol -> deque of prices
        self.positions = {}     # symbol -> {'entry': float, 'sl': float, 'tp': float}

    def _calculate_ema(self, data, window):
        """Calculates Exponential Moving Average."""
        if len(data) < window:
            return None
        
        alpha = 2 / (window + 1)
        # Seed with SMA
        ema = sum(list(data)[:window]) / window
        
        # Iterate
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
        
        avg_gain = sum(gains[-window:]) / window
        avg_loss = sum(losses[-window:]) / window
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _get_volatility(self, data, window):
        """Calculates standard deviation of price for dynamic sizing."""
        if len(data) < window:
            return 0.0
        subset = list(data)[-window:]
        if len(subset) < 2:
            return 0.0
        return statistics.stdev(subset)

    def on_price_update(self, prices):
        """
        Logic:
        1. Parse Data.
        2. Check Static Exits (TP/SL) & Trend Reversals.
        3. Check Entries (Volatility Breakout).
        """
        
        candidates = []
        active_symbols = list(self.positions.keys())
        
        # 1. Ingestion
        for sym, p_data in prices.items():
            try:
                if not p_data or 'priceUsd' not in p_data:
                    continue
                price = float(p_data['priceUsd'])
                liquidity = float(p_data.get('liquidity', 0))
            except (ValueError, TypeError):
                continue

            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.ema_slow_len + 50)
            self.history[sym].append(price)
            
            # Filter candidates
            if sym not in self.positions and len(self.positions) < self.max_positions:
                if liquidity >= self.min_liquidity:
                    candidates.append(sym)

        # 2. Exit Logic (Static Brackets + Trend Invalidation)
        for sym in active_symbols:
            hist = self.history[sym]
            if len(hist) < self.ema_slow_len:
                continue
                
            current_price = hist[-1]
            pos = self.positions[sym]
            
            # A. Static Stop Loss (Capital Preservation)
            if current_price <= pos['sl']:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['FIXED_STOP_LOSS']}
            
            # B. Static Take Profit (Profit Realization)
            if current_price >= pos['tp']:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TAKE_PROFIT_TARGET']}
            
            # C. Trend Invalidation
            # Even if SL/TP isn't hit, if the trend breaks, we bail.
            fast = self._calculate_ema(hist, self.ema_fast_len)
            slow = self._calculate_ema(hist, self.ema_slow_len)
            
            if fast and slow and fast < slow:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TREND_REVERSAL']}

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        random.shuffle(candidates)
        
        for sym in candidates:
            hist = self.history[sym]
            if len(hist) < self.ema_slow_len + 5:
                continue
            
            current_price = hist[-1]
            
            # Calculate Indicators
            fast = self._calculate_ema(hist, self.ema_fast_len)
            slow = self._calculate_ema(hist, self.ema_slow_len)
            rsi = self._calculate_rsi(hist, self.rsi_period)
            vol = self._get_volatility(hist, self.vol_window)
            
            if fast is None or slow is None:
                continue
            
            # === Entry Conditions ===
            
            # 1. Trend Filter: Fast > Slow (Uptrend)
            if fast <= slow:
                continue
                
            # 2. Momentum Quality: RSI must be bullish but not exhausted
            # Adjusted range to ensure we catch the meat of the move
            if rsi < 55 or rsi > 78:
                continue
                
            # 3. Breakout Logic
            # Check if price is breaking above the recent high
            lookback_slice = list(hist)[-(self.vol_window + 1):-1]
            if not lookback_slice:
                continue
            recent_high = max(lookback_slice)
            
            if current_price > recent_high:
                # 4. Volatility Check
                # Ensure we have some volatility to trade, but not infinite risk
                if vol == 0:
                    continue

                # Calculate Static Bracket Levels at moment of entry
                # This ensures we do NOT use trailing logic
                stop_loss_price = current_price - (vol * self.stop_mult)
                take_profit_price = current_price + (vol * self.target_mult)
                
                # Sanity check for SL
                if stop_loss_price <= 0:
                    stop_loss_price = current_price * 0.95

                self.positions[sym] = {
                    'entry': current_price,
                    'sl': stop_loss_price,
                    'tp': take_profit_price
                }
                
                return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['VOL_BREAKOUT']}

        return None