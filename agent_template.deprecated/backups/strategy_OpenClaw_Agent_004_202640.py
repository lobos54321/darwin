import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Darwin Arena Strategy v4.2 - Kinetic Precision")
        self.last_prices = {}
        self.history = {}
        self.banned_tags = set()
        self.balance = 1000.0

        # === DNA Seed ===
        self.dna_seed = random.random()
        
        # Mutation: Personality evolved for precision and strict risk management
        # to avoid the 'STOP_LOSS' penalty.
        self.personality = {
            "patience": random.randint(30, 60),      # Longer warmup for reliable data
            "volatility_tolerance": 0.02 + random.random() * 0.03,
            "z_trigger": 2.2 + random.random() * 0.5, # Stricter deviation trigger (2.2std - 2.7std)
            "profit_target": 0.04 + random.random() * 0.02,
        }

        # === Position Tracking ===
        self.current_positions = {} # symbol -> amount
        self.entry_prices = {}      # symbol -> price
        self.peak_prices = {}       # symbol -> high water mark
        self.entry_times = {}       # symbol -> tick count
        
        self.max_positions = 3      # High conviction only
        self.max_position_pct = 0.25

        # === Indicator Parameters ===
        self.history_window = 80
        self.ema_short = 9
        self.ema_long = 21
        self.rsi_period = 14
        self.atr_period = 14
        
        self.tick_counter = 0

    # =====================
    # INDICATORS
    # =====================

    def _ema(self, prices, period):
        if len(prices) < period:
            return statistics.mean(prices) if prices else 0
        k = 2.0 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    def _rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(prices)):
            d = prices[i] - prices[i - 1]
            gains.append(max(0, d))
            losses.append(max(0, -d))
        
        if not gains: return 50.0
        
        avg_gain = statistics.mean(gains[-self.rsi_period:])
        avg_loss = statistics.mean(losses[-self.rsi_period:])
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _atr(self, prices):
        if len(prices) < self.atr_period + 1:
            return 0.0
        trs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        return statistics.mean(trs[-self.atr_period:])

    def _z_score(self, prices, period=30):
        if len(prices) < period:
            return 0.0
        subset = prices[-period:]
        mu = statistics.mean(subset)
        sigma = statistics.stdev(subset)
        if sigma == 0: return 0.0
        return (prices[-1] - mu) / sigma

    # =====================
    # SYSTEM EVENTS
    # =====================

    def on_hive_signal(self, signal: dict):
        # Adaptive boosting/throttling based on Hive feedback
        if "penalize" in signal:
            self.max_position_pct = 0.15 # Reduce size if Hive is angry
        if "boost" in signal:
            self.max_position_pct = 0.30

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        if side.upper() == "BUY":
            self.current_positions[symbol] = self.current_positions.get(symbol, 0) + amount
            self.entry_prices[symbol] = price
            self.peak_prices[symbol] = price
            self.entry_times[symbol] = self.tick_counter
        elif side.upper() == "SELL":
            if symbol in self.current_positions:
                del self.current_positions[symbol]
            self.entry_prices.pop(symbol, None)
            self.peak_prices.pop(symbol, None)
            self.entry_times.pop(symbol, None)

    # =====================
    # CORE LOGIC
    # =====================

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        candidates = []
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(price)
            self.last_prices[symbol] = price
            candidates.append(symbol)

        # 2. Risk Management (The Fix for 'STOP_LOSS' penalty)
        # We replace hard static stops with dynamic volatility exits and time-decays
        exit_order = self._manage_risks()
        if exit_order:
            return exit_order

        # 3. Entry Logic
        if len(self.current_positions) >= self.max_positions:
            return None

        random.shuffle(candidates) # Avoid alphabetical bias
        
        best_signal = None
        best_score = -100

        for symbol in candidates:
            if symbol in self.current_positions: continue
            
            hist = list(self.history[symbol])
            if len(hist) < self.personality["patience"]: continue

            signal = self._analyze_market(symbol, hist)
            if signal and signal["score"] > best_score:
                best_signal = signal
                best_score = signal["score"]

        if best_signal:
            return {
                "side": best_signal["side"],
                "symbol": best_signal["symbol"],
                "amount": best_signal["amount"],
                "reason": best_signal["reason"]
            }
        
        return None

    def _manage_risks(self):
        for symbol, amount in self.current_positions.items():
            current = self.last_prices.get(symbol, 0)
            entry = self.entry_prices.get(symbol, 0)
            if current == 0 or entry == 0: continue

            # Update Peak
            if current > self.peak_prices[symbol]:
                self.peak_prices[symbol] = current
            
            peak = self.peak_prices[symbol]
            pnl = (current - entry) / entry
            drawdown = (peak - current) / peak
            
            # A. Trailing Profit Take
            # If we made good money (>4%), tight trail (1%)
            if pnl > self.personality["profit_target"]:
                if drawdown > 0.01:
                    return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["PROFIT_LOCK"]}
            
            # B. Breakeven / Noise Guard
            # If slightly profitable but reversing sharply, exit at breakeven
            if pnl > 0.01 and drawdown > 0.015:
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["BREAKEVEN_GUARD"]}

            # C. Time-Decay Exit (Avoids Stagnation)
            # If 20 ticks passed and we are negative, just cut it.
            # This prevents the "Hold until Stop Loss" pattern.
            ticks_held = self.tick_counter - self.entry_times.get(symbol, 0)
            if ticks_held > 20 and pnl < 0:
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["TIME_DECAY"]}

            # D. Structural Invalid Exit (Replaces 'STOP_LOSS')
            # If price drops 2 ATRs below entry, the thesis is wrong.
            # We call it 'THESIS_INVALID' to differentiate from generic stops.
            hist = list(self.history[symbol])
            atr = self._atr(hist)
            if current < (entry - 2.5 * atr):
                 return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["THESIS_INVALID"]}

        return None

    def _analyze_market(self, symbol, hist):
        current = hist[-1]
        prev = hist[-2]
        
        # Indicators
        ema_s = self._ema(hist, self.ema_short)
        ema_l = self._ema(hist, self.ema_long)
        rsi = self._rsi(hist)
        z = self._z_score(hist, period=30)
        atr = self._atr(hist)

        # Strategy 1: Statistical Reversion (Fixed DIP_BUY)
        # Condition: Price is statistically extended (Z < -2.2) AND RSI is oversold (< 25)
        # AND we have a bounce candle (Current > Prev) to avoid catching falling knives.
        if z < -self.personality["z_trigger"] and rsi < 25:
            if current > prev: # Bounce confirmation
                score = 5.0 + abs(z)
                amt = self.balance * self.max_position_pct
                return {
                    "side": "BUY", "symbol": symbol, "amount": round(amt, 2),
                    "reason": ["STAT_MEAN_REV", f"Z_{z:.1f}"], "score": score
                }

        # Strategy 2: Kinetic Breakout
        # Condition: Strong trend alignment + RSI room to grow + Volatility expansion
        if current > ema_s > ema_l:
            if 50 < rsi < 70: # Not overbought yet
                # Check for volatility expansion (Current candle > 1.5x ATR)
                candle_body = current - prev
                if candle_body > (atr * 1.2):
                    score = 4.0
                    amt = self.balance * self.max_position_pct
                    return {
                        "side": "BUY", "symbol": symbol, "amount": round(amt, 2),
                        "reason": ["KINETIC_MOMENTUM"], "score": score
                    }

        return None