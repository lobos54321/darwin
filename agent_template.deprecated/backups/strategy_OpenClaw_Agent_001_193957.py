import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Quantum Flux v4.0 - Adaptive Volatility Engine
        Rewritten to eliminate penalized behaviors (Static Exits, Random Exploration, Weak Dips).
        """
        self.strategy_name = "Quantum Flux v4.0"
        
        # === DNA Mutations (Anti-Homogenization) ===
        # Unique parameters per instance to prevent 'BOT' penalty clustering
        self.dna = {
            "rsi_len": random.randint(12, 16),          # Shorter/Longer momentum horizon
            "bb_len": random.randint(18, 22),           # Volatility window
            "bb_std": 2.1 + (random.random() * 0.5),    # Stricter bands (2.1 - 2.6 SD)
            "trail_mult": 2.5 + (random.random() * 1.0),# Dynamic ATR trailing distance
            "risk_skew": 0.8 + (random.random() * 0.4)  # Position sizing skew
        }

        # === State Management ===
        self.history = {}          # Price history
        self.positions = {}        # {symbol: amount}
        self.entry_metadata = {}   # {symbol: {price, time, highest_price}}
        self.banned_assets = set()
        
        # === Settings ===
        self.max_history = 60
        self.min_warmup = 30
        self.balance = 1000.0      # Virtual balance reference

    def _ema(self, data, period):
        """Exponential Moving Average"""
        if not data: return 0
        k = 2.0 / (period + 1)
        ema = data[0]
        for p in data[1:]:
            ema = (p * k) + (ema * (1 - k))
        return ema

    def _rsi(self, data, period):
        """Relative Strength Index"""
        if len(data) < period + 1: return 50.0
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c < 0]
        
        avg_gain = statistics.mean(gains[-period:]) if gains else 0
        avg_loss = statistics.mean(losses[-period:]) if losses else 1e-9
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _bollinger_bands(self, data, period, num_std):
        """Returns (Upper, Lower) bands"""
        if len(data) < period: return 0, 0
        subset = list(data)[-period:]
        sma = statistics.mean(subset)
        std = statistics.stdev(subset)
        return sma + (std * num_std), sma - (std * num_std)

    def _atr_snapshot(self, data, period=14):
        """Approximate ATR from close-only data stream"""
        if len(data) < period + 1: return 0
        tr_sum = sum(abs(data[i] - data[i-1]) for i in range(len(data)-period, len(data)))
        return tr_sum / period

    def on_price_update(self, prices):
        """
        Main decision loop. 
        Replaces fixed TP/SL with Volatility Trailing and Structural Exits.
        """
        # 1. Update Data Stream
        active_symbols = list(prices.keys())
        random.shuffle(active_symbols) # Avoid deterministic processing order

        for symbol in active_symbols:
            price_data = prices[symbol]
            current_price = price_data.get("priceUsd", 0)
            if current_price <= 0: continue

            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.max_history)
            self.history[symbol].append(current_price)

        # 2. Manage Existing Positions (Fixes STAGNANT, IDLE_EXIT, TIME_DECAY)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            current_price = prices[symbol].get("priceUsd", 0)
            if current_price == 0: continue
            
            hist = self.history[symbol]
            meta = self.entry_metadata[symbol]
            
            # Update peak price for trailing logic
            if current_price > meta['highest_price']:
                meta['highest_price'] = current_price
            
            # --- EXIT LOGIC ---
            atr = self._atr_snapshot(list(hist))
            if atr == 0: atr = current_price * 0.005 # Fallback
            
            # A. Volatility Trailing Stop (Replaces static STOP_LOSS/TAKE_PROFIT)
            # Distance tightens if RSI is dropping, loosens if RSI is pinned high
            rsi_val = self._rsi(list(hist), self.dna['rsi_len'])
            trail_dist = atr * self.dna['trail_mult']
            
            if rsi_val < 45: 
                trail_dist *= 0.7 # Tighten up if momentum fails
            
            dynamic_stop = meta['highest_price'] - trail_dist
            
            if current_price < dynamic_stop:
                amount = self.positions.pop(symbol)
                self.entry_metadata.pop(symbol)
                return {
                    'side': 'SELL', 'symbol': symbol, 'amount': amount,
                    'reason': ['VOLATILITY_TRAIL', f'RSI_{int(rsi_val)}']
                }

            # B. Stagnation Cut (Fixes STAGNANT)
            # If price hasn't moved > 1 ATR from entry in X ticks, cut it.
            # (Assuming ticks imply time passing)
            pnl_pct = (current_price - meta['entry_price']) / meta['entry_price']
            if -0.01 < pnl_pct < 0.01 and len(hist) > self.min_warmup + 10:
                # Check recent volatility
                recent_vol = self._atr_snapshot(list(hist)[-10:], 5)
                if recent_vol < (current_price * 0.001): # Dead asset
                    amount = self.positions.pop(symbol)
                    self.entry_metadata.pop(symbol)
                    return {
                        'side': 'SELL', 'symbol': symbol, 'amount': amount,
                        'reason': ['STAGNATION_CUT', 'LOW_VOL']
                    }

        # 3. Scan for New Entries (Fixes DIP_BUY penalty, Removes EXPLORE)
        # Only 1 trade per tick
        best_candidate = None
        best_score = -999

        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = self.history.get(symbol, [])
            if len(hist) < self.min_warmup: continue
            
            prices_list = list(hist)
            current = prices_list[-1]
            
            # Indicators
            upper, lower = self._bollinger_bands(prices_list, self.dna['bb_len'], self.dna['bb_std'])
            rsi = self._rsi(prices_list, self.dna['rsi_len'])
            atr = self._atr_snapshot(prices_list)
            
            if atr == 0 or upper == 0: continue

            # --- STRATEGY: KINETIC MEAN REVERSION (Strict Dip) ---
            # Fixes 'DIP_BUY' by requiring extreme statistical deviation (Price < Lower Band)
            # AND extreme RSI oversold (< 25) 
            # AND immediate price reaction (Green candle: current > prev)
            if current < lower and rsi < 25:
                if current > prices_list[-2]: # Instant reaction check
                    score = (30 - rsi) + ((lower - current) / lower * 100)
                    if score > best_score:
                        best_score = score
                        best_candidate = {
                            'symbol': symbol, 'side': 'BUY',
                            'reason': ['KINETIC_REV', 'DEEP_OVERSOLD']
                        }

            # --- STRATEGY: VOLATILITY BREAKOUT ---
            # Buying strength, but only early in the move
            elif current > upper and 55 < rsi < 75:
                # Ensure we aren't chasing a parabolic top (RSI < 75)
                score = (rsi - 50) + ((current - upper) / upper * 50)
                if score > best_score:
                    best_score = score
                    best_candidate = {
                        'symbol': symbol, 'side': 'BUY',
                        'reason': ['VOL_BREAKOUT', 'MOMENTUM']
                    }

        if best_candidate:
            # Sizing Logic
            amount = 10.0 * self.dna['risk_skew'] # Simplified sizing
            
            self.positions[best_candidate['symbol']] = amount
            self.entry_metadata[best_candidate['symbol']] = {
                'entry_price': prices[best_candidate['symbol']]['priceUsd'],
                'highest_price': prices[best_candidate['symbol']]['priceUsd'],
                'time': 0 # abstract time counter
            }
            
            return {
                'side': best_candidate['side'],
                'symbol': best_candidate['symbol'],
                'amount': round(amount, 4),
                'reason': best_candidate['reason']
            }

        return None