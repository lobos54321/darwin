import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v4.1 (Adaptive ATR Sentinel)")
        self.last_prices = {}
        self.history = {}
        self.banned_tags = set()
        self.balance = 1000.0

        # === DNA Seed: Unique Mutations ===
        # Mutation: Shift towards volatility-adjusted parameters to fix STOP_LOSS churn
        self.dna_seed = random.random()
        self.personality = {
            "atr_stop_mult": 2.8 + random.random() * 0.7,   # Wider stop (2.8x - 3.5x ATR)
            "atr_profit_mult": 3.5 + random.random() * 1.5, # High reward-to-risk target
            "risk_per_trade": 35.0,
            "ema_fast": random.randint(5, 7),
            "ema_slow": random.randint(13, 16),
            "patience": 15
        }

        # === Position Tracking ===
        self.current_positions = {}  # {symbol: amount}
        self.position_meta = {}      # {symbol: {'entry': float, 'atr': float, 'highest': float}}
        self.max_positions = 3       # Reduced concentration
        self.max_position_pct = 0.2

        # === Indicators Setup ===
        self.history_window = 50
        self.rsi_period = 9  # Faster RSI
        self.stoch_period = 9
        self.atr_period = 14
        
        # === Volatility State ===
        self.global_volatility = 0.0

    def _ema(self, data, period):
        if not data: return 0
        if len(data) < period: return statistics.mean(data)
        k = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price - ema) * k + ema
        return ema

    def _atr(self, prices):
        if len(prices) < 2: return 0
        tr_sum = 0
        # Simplified TR for streaming data (High-Low approximation via abs diff)
        for i in range(1, len(prices)):
            tr_sum += abs(prices[i] - prices[i-1])
        return tr_sum / (len(prices) - 1)

    def _stoch_rsi(self, prices):
        if len(prices) < 20: return 50
        # Calculate recent RSI
        rsi_len = self.rsi_period
        gains, losses = 0.0, 0.0
        # Simple window avg for speed
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        if not changes: return 50
        
        # We only need the last few RSIs to calc StochRSI
        rsi_series = []
        lookback = self.stoch_period + 5
        
        for i in range(lookback):
            idx = len(changes) - lookback + i
            if idx < 0: continue
            
            # Recalculate RSI for this slice (simplified for performance)
            window = changes[max(0, idx-rsi_len):idx+1]
            g = sum(x for x in window if x > 0)
            l = sum(abs(x) for x in window if x < 0)
            rsi = 100 if l == 0 else 100 - (100 / (1 + g/l))
            rsi_series.append(rsi)
            
        if not rsi_series: return 50
        
        min_r = min(rsi_series)
        max_r = max(rsi_series)
        if max_r == min_r: return 50
        return ((rsi_series[-1] - min_r) / (max_r - min_r)) * 100

    def _keltner(self, prices, atr):
        if not prices: return 0, 0, 0
        ema = self._ema(prices, 20)
        # 2.0 multiplier for standard bands
        return ema, ema + (atr * 2.0), ema - (atr * 2.0)

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Update internal state on execution"""
        if side.upper() == "BUY":
            # Snapshot ATR at entry for dynamic stop calculation
            hist = self.history.get(symbol, [])
            entry_atr = self._atr(list(hist)[-15:]) if len(hist) > 15 else price * 0.02
            
            self.current_positions[symbol] = self.current_positions.get(symbol, 0) + amount
            self.position_meta[symbol] = {
                'entry': price,
                'atr': entry_atr,
                'highest': price
            }
        elif side.upper() == "SELL":
            self.current_positions.pop(symbol, None)
            self.position_meta.pop(symbol, None)

    def on_price_update(self, prices: dict):
        symbols = list(prices.keys())
        random.shuffle(symbols)

        # 1. Update History & Global Volatility
        vol_samples = []
        for sym in symbols:
            p = prices[sym]['priceUsd']
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_window)
            self.history[sym].append(p)
            self.last_prices[sym] = p
            
            # Check volatility
            if len(self.history[sym]) > 5:
                vol_samples.append(abs(p - self.history[sym][-2]) / p)

        if vol_samples:
            self.global_volatility = statistics.mean(vol_samples)

        # 2. Phase: Position Management (Fixing STOP_LOSS penalty)
        # We move from fixed % stops to ATR-based dynamic stops.
        for sym in list(self.current_positions.keys()):
            if sym not in self.last_prices: continue
            
            curr_price = self.last_prices[sym]
            meta = self.position_meta.get(sym)
            if not meta: continue

            entry = meta['entry']
            atr = meta['atr']
            amt = self.current_positions[sym]

            # Update Highest High for Trailing
            if curr_price > meta['highest']:
                meta['highest'] = curr_price
                self.position_meta[sym] = meta # Save back

            # Dynamic Thresholds
            # Stop Loss is calculated relative to entry volatility.
            # If we entered in high vol, we give it more room.
            stop_price = entry - (atr * self.personality['atr_stop_mult'])
            
            # Take Profit Target
            target_price = entry + (atr * self.personality['atr_profit_mult'])
            
            # Trailing Stop: Only active if PnL is decent (> 1.5 ATRs)
            trailing_trigger = entry + (atr * 1.5)
            trailing_dist = atr * 0.5
            
            # Logic
            pnl_pct = (curr_price - entry) / entry

            # A. Dynamic Hard Stop (Replaces fixed %)
            if curr_price < stop_price:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amt, 
                    'reason': ['ATR_STOP', f"Entry:{entry:.2f}"]
                }
            
            # B. Dynamic Target
            if curr_price > target_price:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amt,
                    'reason': ['ATR_TARGET_HIT']
                }

            # C. Trailing Stop
            if meta['highest'] > trailing_trigger:
                if curr_price < meta['highest'] - trailing_dist:
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': amt,
                        'reason': ['TRAILING_PROFIT']
                    }

        # 3. Phase: Entry Signals
        if len(self.current_positions) >= self.max_positions:
            return None

        best_signal = None
        best_score = -10.0

        for sym in symbols:
            if sym in self.current_positions: continue
            hist = list(self.history[sym])
            if len(hist) < self.personality['patience']: continue

            # Indicators
            curr = hist[-1]
            prev = hist[-2]
            atr = self._atr(hist[-15:])
            if atr == 0: continue
            
            mid, up, low = self._keltner(hist, atr)
            stoch = self._stoch_rsi(hist)
            ema_f = self._ema(hist, self.personality['ema_fast'])
            ema_s = self._ema(hist, self.personality['ema_slow'])

            score = 0
            signal_tags = []

            # --- Signal A: Confirmed Reversal (Stricter Dip Buy) ---
            # Fix: Require green candle (curr > prev) to avoid catching falling knives
            if curr < low and stoch < 15:
                if curr > prev: # Confirmation
                    score = 2.0
                    signal_tags = ['SMART_DIP', 'CONFIRMED']
            
            # --- Signal B: Momentum Breakout ---
            # Fix: Ensure not overextended (Stoch < 85)
            elif curr > up and ema_f > ema_s:
                if stoch < 85 and curr > prev:
                    score = 1.5
                    signal_tags = ['MOMENTUM_BREAK']

            # Volatility Filter: Reduce score if global market is too chaotic
            if self.global_volatility > 0.02: # >2% moves per tick
                score *= 0.5
            
            if score > best_score and score > 0:
                best_score = score
                # Position Sizing: Inverse Volatility
                # If ATR is high, buy less. If ATR is low, buy more.
                # Base size / (ATR/Price)
                vol_ratio = atr / curr if curr > 0 else 0.01
                safe_size = (self.personality['risk_per_trade'] * 0.01) / max(0.001, vol_ratio)
                safe_size = min(safe_size, self.balance * self.max_position_pct)
                safe_size = max(5.0, safe_size)

                best_signal = {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': round(safe_size, 2),
                    'reason': signal_tags
                }

        return best_signal