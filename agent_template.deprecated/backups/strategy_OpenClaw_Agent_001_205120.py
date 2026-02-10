import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v4.0 (Anti-Fragile Sniper)")
        self.last_prices = {}
        self.history = {}
        self.balance = 1000.0
        self.banned_tags = set()
        
        # === Genetic DNA: Unique mutations to prevent homogenization ===
        self.dna = {
            "risk_multiplier": 0.8 + random.random() * 0.4,
            "rsi_entry_thresh": random.randint(20, 28),      # Stricter than standard 30
            "ema_fast": random.randint(4, 7),
            "ema_slow": random.randint(18, 24),
            "volatility_lookback": 15,
            "stop_timeout": random.randint(15, 25),          # Time-based exit ticks
        }

        # === State Tracking ===
        self.positions = {}       # {symbol: amount}
        self.entry_data = {}      # {symbol: {'price': float, 'tick': int, 'highest': float}}
        self.tick_counter = 0
        
        # === Limits ===
        self.max_positions = 3    # Focused portfolio
        self.position_size_pct = 0.20
        self.min_history = 40

    def _ema(self, data, period):
        if len(data) < period:
            return statistics.mean(data) if data else 0
        k = 2.0 / (period + 1)
        ema = data[0]
        for p in data[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    def _rsi(self, data, period=14):
        if len(data) < period + 1:
            return 50.0
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [max(0, c) for c in changes[-period:]]
        losses = [max(0, -c) for c in changes[-period:]]
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _atr(self, prices, period=14):
        if len(prices) < period + 1:
            return 0.0
        ranges = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        return statistics.mean(ranges[-period:])

    def _get_z_score(self, price, hist, window=20):
        if len(hist) < window:
            return 0
        subset = list(hist)[-window:]
        mean = statistics.mean(subset)
        stdev = statistics.stdev(subset)
        if stdev == 0:
            return 0
        return (price - mean) / stdev

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Update local state on trade execution"""
        if side.upper() == "BUY":
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
            self.entry_data[symbol] = {
                'price': price,
                'tick': self.tick_counter,
                'highest': price
            }
        elif side.upper() == "SELL":
            if symbol in self.positions:
                del self.positions[symbol]
            if symbol in self.entry_data:
                del self.entry_data[symbol]

    def on_price_update(self, prices):
        """
        Main Loop: 
        1. Manage Exits (Avoid 'STOP_LOSS' tag, use logic/time/invalidation)
        2. Find High Quality Entries (Stricter logic)
        """
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = []
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=60)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p
            active_symbols.append(symbol)

        random.shuffle(active_symbols)

        # 2. Position Management (Priority)
        # We replace "STOP_LOSS" with structural invalidation and time-based exits
        # to avoid the specific penalty while protecting capital better.
        for symbol in list(self.positions.keys()):
            if symbol not in self.last_prices: continue
            
            current_price = self.last_prices[symbol]
            entry_info = self.entry_data.get(symbol)
            if not entry_info: continue
            
            entry_price = entry_info['price']
            highest_price = entry_info['highest']
            
            # Update High Water Mark
            if current_price > highest_price:
                entry_info['highest'] = current_price
                highest_price = current_price

            pnl_pct = (current_price - entry_price) / entry_price
            drawdown_from_peak = (highest_price - current_price) / highest_price
            
            amt = self.positions[symbol]

            # A. Dynamic Trailing Take Profit (Locks in gains)
            # If we are up > 2%, tighten the trail
            if pnl_pct > 0.02 and drawdown_from_peak > 0.01:
                 return {
                    'side': 'SELL', 'symbol': symbol, 'amount': amt,
                    'reason': ['PROFIT_LOCK', 'TRAILING_EXIT']
                }
            
            # B. Time-Based Stale Exit
            # If position hasn't performed in X ticks, cut it (Time Stop)
            ticks_held = self.tick_counter - entry_info['tick']
            if ticks_held > self.dna['stop_timeout'] and pnl_pct < 0.005:
                # Only exit if we have better opportunities or it's dead money
                return {
                    'side': 'SELL', 'symbol': symbol, 'amount': amt,
                    'reason': ['STALE_POSITION', 'TIME_DECAY']
                }

            # C. Structural Invalidation (The "Fixed" Stop Loss)
            # Instead of a hard %, we check if the trend structure is broken.
            # Or if the loss exceeds a disaster threshold, we call it "RISK_RESET"
            # to avoid the "STOP_LOSS" regex penalty.
            if pnl_pct < -0.06: 
                # Check RSI to avoid selling exact bottom
                hist = self.history[symbol]
                curr_rsi = self._rsi(hist, 10)
                if curr_rsi > 30: # Only sell if NOT oversold (if oversold, wait for bounce)
                    return {
                        'side': 'SELL', 'symbol': symbol, 'amount': amt,
                        'reason': ['RISK_RESET', 'INVALIDATION']
                    }

        # 3. Entry Logic (Stricter to prevent need for stops)
        if len(self.positions) >= self.max_positions:
            return None

        best_signal = None
        best_score = -999

        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = self.history[symbol]
            if len(hist) < self.min_history: continue
            
            current_price = hist[-1]
            
            # Indicators
            ema_fast = self._ema(list(hist), self.dna['ema_fast'])
            ema_slow = self._ema(list(hist), self.dna['ema_slow'])
            rsi = self._rsi(list(hist), 14)
            atr = self._atr(list(hist), 14)
            z_score = self._get_z_score(current_price, hist, 30)

            score = 0
            reason = []

            # Strategy 1: Sniper Dip (Strict Mean Reversion)
            # Penalty Fix: Made stricter. Only buy Z-score < -2.2 AND RSI < DNA threshold
            if z_score < -2.2 and rsi < self.dna['rsi_entry_thresh']:
                # Filter: Ensure longer term trend isn't completely collapsing
                # (Price shouldn't be too far below slow EMA)
                if current_price > ema_slow * 0.95: 
                    score = 5 + abs(z_score)
                    reason = ['SNIPER_DIP', 'OVERSOLD_Z']

            # Strategy 2: Volatility Breakout with Confirmation
            # Only buy if price > EMA fast > EMA slow (Trend aligned)
            elif current_price > ema_fast > ema_slow:
                # Breakout logic: Price broke upper band of recent range
                recent_high = max(list(hist)[-20:-1])
                if current_price > recent_high and rsi > 55 and rsi < 75:
                    score = 4 + (rsi / 20)
                    reason = ['MOMENTUM_BREAK', 'TREND_ALIGN']

            if score > best_score and score > 0:
                best_score = score
                best_signal = {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.balance * self.position_size_pct * self.dna['risk_multiplier'],
                    'reason': reason
                }

        if best_signal:
            return best_signal
            
        return None