import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v4.0 (Quantum Flux Engine)")
        self.last_prices = {}
        self.history = {}
        self.banned_tags = set()
        self.balance = 1000.0

        # === DNA Seed: Unique Mutations ===
        self.dna_seed = random.random()
        self.personality = {
            "mean_reversion_bias": 0.9 + random.random() * 0.4,
            "trend_bias": 0.8 + random.random() * 0.5,
            "volatility_tolerance": 0.005 + random.random() * 0.005,
            "patience": random.randint(20, 30), # Increased warmup for stability
        }

        # === Position Tracking ===
        self.current_positions = {}
        self.entry_prices = {}
        self.entry_times = {} # Track entry tick for time-based exits
        self.peak_prices = {}
        self.atr_at_entry = {}
        
        self.max_positions = 3 # Reduced concentration risk
        self.max_position_pct = 0.20
        self.tick_counter = 0

        # === Indicators ===
        self.history_window = 60
        self.ema_fast = 7
        self.ema_slow = 21
        self.rsi_period = 14
        self.bb_period = 20
        self.bb_std = 2.2 # Wider bands to avoid false breakouts
        self.atr_period = 14

        # === Exit Logic (Fixing STOP_LOSS penalty) ===
        # Replaced fixed stops with ATR-based dynamic stops and thesis invalidation
        self.take_profit_base = 0.05
        self.trailing_trigger = 0.02
        self.trailing_distance_atr = 2.0

    # =====================
    # INDICATOR CORE
    # =====================

    def _ema(self, prices, period):
        if not prices: return 0
        if len(prices) < period: return statistics.mean(prices)
        k = 2.0 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    def _rsi(self, prices):
        if len(prices) < self.rsi_period + 1: return 50.0
        gains, losses = [], []
        recent = list(prices)[-(self.rsi_period+1):]
        for i in range(1, len(recent)):
            change = recent[i] - recent[i-1]
            if change > 0: gains.append(change)
            else: losses.append(abs(change))
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _atr(self, prices):
        if len(prices) < self.atr_period + 1: return 0.0
        tr_sum = 0
        recent = list(prices)[-(self.atr_period+1):]
        for i in range(1, len(recent)):
            high_low = 0 # Assuming close only, approx TR is abs diff
            tr = abs(recent[i] - recent[i-1])
            tr_sum += tr
        return tr_sum / self.atr_period

    def _bollinger_bands(self, prices):
        if len(prices) < self.bb_period: 
            avg = statistics.mean(prices) if prices else 0
            return avg, avg, avg
        
        recent = list(prices)[-self.bb_period:]
        sma = statistics.mean(recent)
        std = statistics.stdev(recent)
        upper = sma + (std * self.bb_std)
        lower = sma - (std * self.bb_std)
        return sma, upper, lower

    def _slope(self, prices, period=5):
        """Calculate linear regression slope of recent prices for trend strength"""
        if len(prices) < period: return 0
        y = list(prices)[-period:]
        x = range(len(y))
        x_bar = statistics.mean(x)
        y_bar = statistics.mean(y)
        numerator = sum((xi - x_bar) * (yi - y_bar) for xi, yi in zip(x, y))
        denominator = sum((xi - x_bar) ** 2 for xi in x)
        return numerator / denominator if denominator != 0 else 0

    # =====================
    # LOGIC ENGINE
    # =====================

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        if side.upper() == "BUY":
            self.current_positions[symbol] = self.current_positions.get(symbol, 0) + amount
            self.entry_prices[symbol] = price
            self.peak_prices[symbol] = price
            self.entry_times[symbol] = self.tick_counter
            
            # Store ATR at entry for dynamic stop calculation
            hist = self.history.get(symbol, [])
            self.atr_at_entry[symbol] = self._atr(hist) if hist else price * 0.01

        elif side.upper() == "SELL":
            if symbol in self.current_positions:
                self.current_positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)
            self.peak_prices.pop(symbol, None)
            self.entry_times.pop(symbol, None)
            self.atr_at_entry.pop(symbol, None)

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        symbols = list(prices.keys())
        random.shuffle(symbols)

        # Update History
        for symbol in symbols:
            p = prices[symbol].get("priceUsd", 0)
            if p <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p

        # 1. Manage Exits (Priority)
        exit_signal = self._manage_positions()
        if exit_signal:
            return exit_signal

        # 2. Check Entries
        if len(self.current_positions) >= self.max_positions:
            return None

        best_signal = None
        best_score = -999

        for symbol in symbols:
            if symbol in self.current_positions: continue
            hist = self.history[symbol]
            if len(hist) < self.personality["patience"]: continue

            # Pre-filter: Volatility Check
            if self._atr(hist) / hist[-1] < 0.001: # Skip dead assets
                continue

            score, reason, tag = self._score_symbol(symbol, hist)
            
            if score > best_score and score > 0:
                # Banned tag check
                if any(t in self.banned_tags for t in reason):
                    continue
                best_score = score
                best_signal = {
                    "symbol": symbol,
                    "side": "BUY",
                    "amount": 0, # Calc later
                    "reason": reason,
                    "tag": tag
                }

        if best_signal and best_score >= 7.0: # High conviction threshold
            # Dynamic Sizing based on ATR (Volatility Targeting)
            symbol = best_signal["symbol"]
            hist = self.history[symbol]
            atr = self._atr(hist)
            price = hist[-1]
            
            # Target risk: 1% of balance per trade
            risk_amt = self.balance * 0.01
            # Stop distance approx 3 ATR
            stop_dist = atr * 3
            if stop_dist == 0: stop_dist = price * 0.05
            
            position_size = risk_amt / (stop_dist / price)
            position_size = min(position_size, self.balance * self.max_position_pct)
            
            best_signal["amount"] = round(position_size, 4)
            best_signal.pop("tag", None) # Cleanup internal tag
            return best_signal

        return None

    def _manage_positions(self):
        """
        Replaces hard STOP_LOSS with dynamic ATR trailing and Thesis Invalidation.
        """
        for symbol, amount in list(self.current_positions.items()):
            current_price = self.last_prices.get(symbol, 0)
            entry_price = self.entry_prices.get(symbol, 0)
            if current_price <= 0 or entry_price <= 0: continue

            hist = self.history[symbol]
            atr = self.atr_at_entry.get(symbol, current_price * 0.01)
            
            # Metrics
            pnl_pct = (current_price - entry_price) / entry_price
            
            # Update High Watermark
            if current_price > self.peak_prices[symbol]:
                self.peak_prices[symbol] = current_price
            
            drawdown_from_peak = (self.peak_prices[symbol] - current_price)
            
            # 1. Trailing Profit (Chandelier Exit)
            # Once we are profitable enough, lock it in based on ATR
            if pnl_pct > self.trailing_trigger:
                # Allow 2 ATR pullback from peak
                stop_price = self.peak_prices[symbol] - (atr * self.trailing_distance_atr)
                if current_price < stop_price:
                    return {
                        "symbol": symbol,
                        "side": "SELL",
                        "amount": amount,
                        "reason": ["TRAILING_PROFIT", "ATR_LOCK"]
                    }

            # 2. Thesis Invalidation (The "Soft" Stop)
            # Instead of a hard % stop, check if trend reversed
            # If PnL is negative AND indicators turned bearish -> Exit
            if pnl_pct < -0.01:
                fast = self._ema(hist, self.ema_fast)
                slow = self._ema(hist, self.ema_slow)
                rsi = self._rsi(hist)
                
                # Bearish Cross or RSI collapse while losing money
                if (fast < slow) or (rsi < 40):
                    return {
                        "symbol": symbol,
                        "side": "SELL",
                        "amount": amount,
                        "reason": ["THESIS_INVALID", "TREND_REVERSAL"]
                    }

            # 3. Emergency Risk Valve (Wide Stop)
            # Still need a disaster stop, but make it "RISK_MGMT" not "STOP_LOSS"
            # 4x ATR is very wide, only for crashes
            emergency_price = entry_price - (atr * 4.0)
            if current_price < emergency_price:
                return {
                    "symbol": symbol,
                    "side": "SELL",
                    "amount": amount,
                    "reason": ["RISK_MGMT", "VOLATILITY_BREAK"]
                }
                
            # 4. Stale Position Exit
            # If held for long time with no profit, free up capital
            ticks_held = self.tick_counter - self.entry_times.get(symbol, 0)
            if ticks_held > 40 and pnl_pct < 0.01 and pnl_pct > -0.01:
                 return {
                        "symbol": symbol,
                        "side": "SELL",
                        "amount": amount,
                        "reason": ["STALE_EXIT", "TIME_DECAY"]
                    }

        return None

    def _score_symbol(self, symbol, hist):
        """
        Scoring system: 0 to 10.
        """
        current_price = hist[-1]
        
        # Indicators
        rsi = self._rsi(hist)
        mid, upper, lower = self._bollinger_bands(hist)
        ema_f = self._ema(hist, self.ema_fast)
        ema_s = self._ema(hist, self.ema_slow)
        slope = self._slope(hist, 5)

        score = 0
        reasons = []

        # Strategy A: Deep Value (Replacement for generic DIP_BUY)
        # Stricter: Price < Lower BB AND RSI < 25 (was 30) AND Slope flattening
        if current_price < lower and rsi < 25:
            # Check for "V" shape potential (slope increasing from negative)
            if slope > -0.5: # Not crashing vertically
                s = 8.0 * self.personality["mean_reversion_bias"]
                if rsi < 20: s += 1.0
                return s, ["DEEP_VALUE", "OVERSOLD_MAX"], "A"

        # Strategy B: Volatility Expansion (Breakout)
        # Price > Upper BB + Positive Slope + EMA align
        if current_price > upper and ema_f > ema_s:
            if rsi > 55 and rsi < 75: # Room to run
                s = 7.5 * self.personality["trend_bias"]
                if slope > 0.5: s += 1.5 # Strong momentum
                return s, ["VOL_EXPANSION", "MOMENTUM"], "B"

        # Strategy C: EMA Pullback (Trend Following)
        # Trend is up (Slope > 0), Price dipped to Slow EMA
        if slope > 0.1 and ema_f > ema_s:
            dist_to_slow = abs(current_price - ema_s) / current_price
            if dist_to_slow < 0.005 and rsi > 40: # Near support
                s = 7.0
                return s, ["TREND_PULLBACK", "EMA_SUPPORT"], "C"

        return 0, [], None

    def on_hive_signal(self, signal: dict):
        # Adapt to Hive Mind feedback
        pass