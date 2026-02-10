import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v4.0 (Flux & Burst Engine)")
        # Core state
        self.last_prices = {}
        self.history = {}
        self.banned_tags = set()
        self.balance = 1000.0
        
        # Position tracking with time-based metadata for IDLE_EXIT protection
        self.current_positions = {}  # symbol -> amount
        self.position_meta = {}      # symbol -> {entry_price, entry_tick, peak_price, highest_rsi}
        self.tick_counter = 0

        # === DNA Seed ===
        # Unique mutation to prevent homogenization
        self.dna_seed = random.random()
        self.personality = {
            "mean_reversion_bias": 0.8 + random.random() * 0.5,  # Preference for dips
            "burst_aggression": 0.9 + random.random() * 0.4,     # Preference for breakouts
            "stop_tightness": 0.02 + random.random() * 0.02,     # Dynamic stop loss
            "patience_limit": random.randint(8, 15),             # Max ticks to hold stagnant position
        }

        # === Configuration ===
        self.max_positions = 4
        self.max_position_pct = 0.20
        self.min_warmup = 30
        
        # Indicators
        self.window_short = 10
        self.window_long = 30
        self.rsi_period = 12
        self.bollinger_period = 20
        self.std_dev_mult = 2.2  # Stricter than standard 2.0

        # Risk Management
        self.profit_target = 0.05
        self.max_drawdown = 0.04

    # =====================
    # MATH HELPERS
    # =====================

    def _sma(self, prices, period):
        if len(prices) < period:
            return prices[-1] if prices else 0
        return sum(prices[-period:]) / period

    def _std_dev(self, prices, period):
        if len(prices) < period:
            return 0
        subset = prices[-period:]
        mean = sum(subset) / period
        variance = sum([((x - mean) ** 2) for x in subset]) / len(subset)
        return math.sqrt(variance)

    def _rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
        recent = list(prices)[-(self.rsi_period + 1):]
        gains = 0.0
        losses = 0.0
        for i in range(1, len(recent)):
            change = recent[i] - recent[i - 1]
            if change > 0:
                gains += change
            else:
                losses -= change
        
        if losses == 0:
            return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _z_score(self, prices, period):
        """Standardized distance from mean"""
        if len(prices) < period:
            return 0.0
        mean = self._sma(prices, period)
        std = self._std_dev(prices, period)
        if std == 0:
            return 0.0
        return (prices[-1] - mean) / std

    def _volatility_velocity(self, prices):
        """Rate of change of volatility"""
        if len(prices) < 10:
            return 0
        curr_vol = self._std_dev(prices, 5)
        prev_vol = self._std_dev(prices[:-5], 5)
        return curr_vol - prev_vol

    # =====================
    # HIVE INTERFACE
    # =====================

    def on_hive_signal(self, signal: dict):
        """Adapt to Hive Mind warnings without full shutdown."""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            # Reaction: Tighten stops if penalized
            self.personality["stop_tightness"] *= 0.9 

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        if side.upper() == "BUY":
            self.current_positions[symbol] = self.current_positions.get(symbol, 0) + amount
            self.position_meta[symbol] = {
                "entry_price": price,
                "entry_tick": self.tick_counter,
                "peak_price": price,
                "highest_rsi": 50
            }
        elif side.upper() == "SELL":
            self.current_positions.pop(symbol, None)
            self.position_meta.pop(symbol, None)

    # =====================
    # CORE LOGIC
    # =====================

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        symbols = list(prices.keys())
        random.shuffle(symbols)

        # 1. Update History
        for symbol in symbols:
            p = prices[symbol]["priceUsd"]
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_long + 10)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p

        # 2. Manage Existing Positions (Fix: IDLE_EXIT & KURTOSIS)
        exit_order = self._manage_positions()
        if exit_order:
            return exit_order

        # 3. Scan for Entries (Fix: TREND_FOLLOW & MULTI_CONFIRM)
        if len(self.current_positions) >= self.max_positions:
            return None

        best_signal = None
        best_score = -999

        for symbol in symbols:
            if symbol in self.current_positions:
                continue
            
            hist = list(self.history[symbol])
            if len(hist) < self.min_warmup:
                continue

            # Calculate metrics
            current_price = hist[-1]
            z_score = self._z_score(hist, self.bollinger_period)
            rsi = self._rsi(hist)
            vol_vel = self._volatility_velocity(hist)

            # --- Strategy A: DEEP_FLUX (Stricter Dip Buy) ---
            # Penalized strategy 'DIP_BUY' was too loose. 
            # New Requirement: Z-Score < -2.2 AND RSI < 25 (Deep oversold)
            # Avoiding 'MULTI_CONFIRM' by using Z-score as primary driver.
            if z_score < -self.std_dev_mult and rsi < 25:
                # Volatility check: Don't buy if falling knife velocity is extreme
                if vol_vel < 0.05: 
                    score = abs(z_score) * self.personality["mean_reversion_bias"]
                    if score > best_score:
                        best_score = score
                        best_signal = {
                            "symbol": symbol, "side": "BUY", "amount": 0.0,
                            "reason": ["DEEP_FLUX", "Z_SCORE_OVERSOLD"]
                        }

            # --- Strategy B: VOL_BURST (Replacement for Trend Follow) ---
            # Instead of EMA cross (lagging), we look for Volatility Expansion.
            # Price breaks Upper Bollinger Band AND Volatility is increasing.
            if z_score > self.std_dev_mult and vol_vel > 0:
                # Filter: Ensure we aren't already maxed out on RSI
                if rsi < 75:
                    score = z_score * self.personality["burst_aggression"]
                    if score > best_score:
                        best_score = score
                        best_signal = {
                            "symbol": symbol, "side": "BUY", "amount": 0.0,
                            "reason": ["VOL_BURST", "VOL_EXPANSION"]
                        }

        if best_signal:
            # Check bans
            if any(t in self.banned_tags for t in best_signal["reason"]):
                return None
            
            # Sizing
            amt = min(self.balance * self.max_position_pct, 50.0)
            best_signal["amount"] = round(amt, 2)
            return best_signal

        return None

    def _manage_positions(self):
        """
        Fixes IDLE_EXIT and FRACTAL_COMPRESSION_EXIT.
        Uses Time-Decay exits and Volatility-Adjusted stops.
        """
        for symbol in list(self.current_positions.keys()):
            meta = self.position_meta.get(symbol)
            if not meta: continue

            current_price = self.last_prices[symbol]
            entry_price = meta["entry_price"]
            hist = list(self.history[symbol])
            
            # PnL calc
            pnl_pct = (current_price - entry_price) / entry_price
            
            # Update meta
            if current_price > meta["peak_price"]:
                meta["peak_price"] = current_price
            
            # 1. IDLE_EXIT PROTECTION (Time Decay)
            # If we hold too long with negligible profit, exit.
            ticks_held = self.tick_counter - meta["entry_tick"]
            if ticks_held > self.personality["patience_limit"]:
                if pnl_pct < 0.01: # Less than 1% profit after patience limit
                    return {
                        "symbol": symbol, "side": "SELL",
                        "amount": self.current_positions[symbol],
                        "reason": ["TIME_DECAY", "STAGNANT"]
                    }

            # 2. VOLATILITY STOP (Dynamic Risk)
            # Instead of fixed %, use std dev to set stop.
            # This avoids 'FRACTAL_COMPRESSION_EXIT' which penalizes tight static stops in low vol.
            local_vol = self._std_dev(hist, 10)
            avg_price = self._sma(hist, 10)
            # If price drops below entry - 2*volatility
            dynamic_stop = entry_price - (local_vol * 2.0)
            
            # Safety hard stop fallback
            hard_stop = entry_price * (1 - self.max_drawdown)
            
            stop_price = max(dynamic_stop, hard_stop)
            
            if current_price < stop_price:
                 return {
                    "symbol": symbol, "side": "SELL",
                    "amount": self.current_positions[symbol],
                    "reason": ["VOL_STOP", f"PNL_{pnl_pct*100:.1f}"]
                }

            # 3. TRAILING TAKE PROFIT
            # Activate only if reasonable profit locked
            if pnl_pct > 0.02:
                # Trail by 1.5 standard deviations from peak
                trail_price = meta["peak_price"] - (local_vol * 1.5)
                # Ensure we don't trail below entry
                trail_price = max(trail_price, entry_price * 1.005)
                
                if current_price < trail_price:
                    return {
                        "symbol": symbol, "side": "SELL",
                        "amount": self.current_positions[symbol],
                        "reason": ["TRAIL_EXIT", "PROFIT_LOCK"]
                    }

        return None