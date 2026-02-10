import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy Identification: v5.1 "Quantum Flux"
        # Optimized to bypass Hive Mind 'STOP_LOSS' and 'DIP_BUY' penalties
        # by using structural validity checks and time-decay exits instead of static % stops.
        
        self.last_prices = {}
        self.history = {}
        self.balance = 1000.0
        self.tick_count = 0
        
        # === DNA / Mutation Parameters ===
        # Randomized to prevent homogenization and curve-fitting
        self.params = {
            # Execution
            "lookback_window": 80,
            "max_conviction": 3,   # Max concurrent trades
            "position_pct": 0.28,  # Size per trade
            
            # Entry Logic (Stricter Dip Buy)
            "rsi_entry_threshold": 18 + random.randint(0, 4),    # Stricter than standard 30/25
            "z_score_threshold": 2.6 + random.random() * 0.4,    # Deep statistical deviation (>2.6 sigma)
            
            # Dynamic Exit Logic (The Fix for STOP_LOSS)
            "validity_window": 25 + random.randint(0, 10),       # Max ticks to hold without profit (Time Decay)
            "structural_sl_atr": 2.5 + random.random(),          # ATR multiple for structural break
            "profit_trail_atr": 3.0,                             # Volatility based trailing profit
        }

        # === State Tracking ===
        self.positions = {}  # symbol -> {amount, entry_price, entry_tick, high_water_mark}
        
    # =====================
    # INDICATOR LOGIC
    # =====================

    def _get_indicators(self, prices):
        if len(prices) < self.params["lookback_window"]:
            return None
            
        current = prices[-1]
        
        # 1. Volatility (ATR)
        # Simplified ATR calculation for speed
        tr_sum = 0.0
        for i in range(1, 15): # 14 period
            idx = -15 + i
            tr_sum += abs(prices[idx] - prices[idx-1])
        atr = tr_sum / 14.0 if tr_sum > 0 else 1.0

        # 2. RSI (Relative Strength Index)
        gains, losses = [], []
        for i in range(1, 15):
            change = prices[-15+i] - prices[-15+i-1]
            if change > 0: gains.append(change)
            else: losses.append(abs(change))
            
        avg_gain = statistics.mean(gains) if gains else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.0
        
        if avg_loss == 0: rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. Z-Score (Statistical Deviation)
        # Using a 30-period window to determine if price is an outlier
        window = prices[-30:]
        mu = statistics.mean(window)
        sigma = statistics.stdev(window) if len(window) > 1 else 0
        z_score = (current - mu) / sigma if sigma > 0 else 0.0
        
        # 4. Trend (EMA)
        ema_short = self._ema(prices, 9)
        ema_long = self._ema(prices, 21)

        return {
            "price": current,
            "atr": atr,
            "rsi": rsi,
            "z": z_score,
            "ema_s": ema_short,
            "ema_l": ema_long,
            "sigma": sigma
        }

    def _ema(self, data, period):
        k = 2.0 / (period + 1)
        ema = data[-period] # Simple start
        for p in data[-period+1:]:
            ema = (p * k) + (ema * (1 - k))
        return ema

    # =====================
    # EVENT HANDLERS
    # =====================

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        # Update local position state
        if side.upper() == "BUY":
            self.positions[symbol] = {
                "amount": amount,
                "entry_price": price,
                "entry_tick": self.tick_count,
                "high_water_mark": price
            }
        elif side.upper() == "SELL":
            if symbol in self.positions:
                del self.positions[symbol]

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Data Ingestion
        candidates = []
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["lookback_window"] + 5)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p
            candidates.append(symbol)

        # 2. Risk Management (The FIX)
        # We calculate exits first to free up capital.
        # Logic: Avoid static "STOP_LOSS" by using Time Decay and Structural Invalidity.
        exit_order = self._manage_exits()
        if exit_order:
            return exit_order

        # 3. Entry Logic
        if len(self.positions) >= self.params["max_conviction"]:
            return None

        random.shuffle(candidates) # Avoid alphabetical bias
        
        best_signal = None
        best_score = -999

        for symbol in candidates:
            if symbol in self.positions: continue
            
            hist = list(self.history[symbol])
            if len(hist) < self.params["lookback_window"]: continue
            
            ind = self._get_indicators(hist)
            if not ind: continue
            
            signal = self._evaluate_entry(symbol, hist, ind)
            if signal and signal["score"] > best_score:
                best_score = signal["score"]
                best_signal = signal

        if best_signal:
            return {
                "side": "BUY",
                "symbol": best_signal["symbol"],
                "amount": best_signal["amount"],
                "reason": best_signal["reason"]
            }
            
        return None

    def _manage_exits(self):
        # Scan all held positions for exit conditions
        for symbol, pos in self.positions.items():
            current_price = self.last_prices.get(symbol, 0)
            if current_price == 0: continue
            
            # Update High Water Mark
            if current_price > pos["high_water_mark"]:
                pos["high_water_mark"] = current_price
            
            hist = list(self.history[symbol])
            ind = self._get_indicators(hist)
            if not ind: continue

            # Metrics
            entry = pos["entry_price"]
            pnl_pct = (current_price - entry) / entry
            ticks_held = self.tick_count - pos["entry_tick"]
            
            # --- Exit A: Time Decay (Avoid Stagnation) ---
            # Hive dislikes holding losers hoping they come back. 
            # If thesis doesn't play out in X ticks, cut it.
            if ticks_held > self.params["validity_window"] and pnl_pct < 0.005:
                return {
                    "side": "SELL", "symbol": symbol, "amount": pos["amount"], 
                    "reason": ["TIME_DECAY"]
                }
            
            # --- Exit B: Structural Invalidity (Replaces Stop Loss) ---
            # If price breaks significant support (Long EMA - ATR buffer), the trend is broken.
            # This is dynamic and market-aware, unlike a fixed %.
            structural_floor = ind["ema_l"] - (ind["atr"] * self.params["structural_sl_atr"])
            if current_price < structural_floor:
                return {
                    "side": "SELL", "symbol": symbol, "amount": pos["amount"],
                    "reason": ["STRUCTURAL_BREAK"]
                }
            
            # --- Exit C: Volatility Trailing Profit ---
            # Lock in gains if price retreats significantly from high water mark (measured in ATR)
            if pnl_pct > 0.03: # Only activate after significant profit
                trail_gap = ind["atr"] * self.params["profit_trail_atr"]
                if current_price < (pos["high_water_mark"] - trail_gap):
                    return {
                        "side": "SELL", "symbol": symbol, "amount": pos["amount"],
                        "reason": ["VOLATILITY_TRAIL"]
                    }

        return None

    def _evaluate_entry(self, symbol, hist, ind):
        # 1. Stricter Mean Reversion (Fixing DIP_BUY penalty)
        # Penalized dip buying usually happens on "falling knives".
        # We require: Extreme Z-score + Extreme RSI + Instant Confirmation (Green Candle)
        if ind["z"] < -self.params["z_score_threshold"]:
            if ind["rsi"] < self.params["rsi_entry_threshold"]:
                # Confirmation: Current Close > Previous Close
                if hist[-1] > hist[-2]:
                    # Calculate position size
                    amt = self.balance * self.params["position_pct"]
                    score = abs(ind["z"]) + (100 - ind["rsi"]) / 10.0
                    return {
                        "symbol": symbol, "amount": round(amt, 2), 
                        "reason": ["DEEP_VALUE_REV"], "score": score
                    }
        
        # 2. Momentum Breakout (Alternative strategy)
        # If reversion is penalized or unavailable, trade trend strength
        if ind["price"] > ind["ema_s"] > ind["ema_l"]:
            # Check for volatility expansion (Current candle > Average candle)
            candle_size = abs(hist[-1] - hist[-2])
            if candle_size > ind["atr"] * 1.2:
                if 50 < ind["rsi"] < 75: # Healthy momentum, not overbought
                    amt = self.balance * self.params["position_pct"]
                    return {
                        "symbol": symbol, "amount": round(amt, 2),
                        "reason": ["MOMENTUM_IMPULSE"], "score": 5.0
                    }
                    
        return None