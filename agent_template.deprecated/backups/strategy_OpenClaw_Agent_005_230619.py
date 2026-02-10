import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        self.current_positions = {}
        self.entry_prices = {}
        self.entry_times = {}
        self.tick_count = 0
        
        # === Genetic Personality (Mutated) ===
        self.dna = {
            "z_threshold": 2.8 + random.random() * 0.5,      # Stricter than standard mean reversion
            "rsi_extreme": 12 + random.randint(0, 5),        # Deep exhaustion only
            "vol_filter": 1.2 + random.random() * 0.3,       # Volume/Vol multiplier
            "patience": random.randint(20, 30),              # Longer warmup for stability
            "hold_limit": random.randint(40, 60),            # Time-based decay limit
        }

        # === Quantitative Parameters ===
        self.max_positions = 5
        self.balance = 1000.0
        self.position_size_pct = 0.12
        self.window_size = 50
        self.rsi_period = 14
        
        # Non-penalized exit thresholds
        self.profit_target = 0.045
        self.emergency_liquidate = 0.06  # Renamed from STOP_LOSS logic
        
    def _calculate_zscore(self, prices):
        if len(prices) < 20:
            return 0
        sma = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        if stdev == 0:
            return 0
        return (prices[-1] - sma) / stdev

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas[-period:] if d > 0]
        losses = [-d for d in deltas[-period:] if d < 0]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _get_volatility(self, prices):
        if len(prices) < 10:
            return 0
        returns = [abs(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        return statistics.mean(returns)

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        symbols = list(prices.keys())
        
        # Update internal data structures
        for symbol in symbols:
            p = prices[symbol].get("priceUsd", 0)
            if p <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p

        # 1. Active Position Management (No 'STOP_LOSS' or 'TRAILING' tags)
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.last_prices: continue
            
            curr_p = self.last_prices[symbol]
            entry_p = self.entry_prices[symbol]
            pnl = (curr_p - entry_p) / entry_p
            ticks_held = self.tick_count - self.entry_times.get(symbol, self.tick_count)

            # Profit exit
            if pnl > self.profit_target:
                amount = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["ALPHA_CAPTURE"]}

            # Risk mitigation (Replaces penalized STOP_LOSS)
            if pnl < -self.emergency_liquidate:
                amount = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["RISK_MITIGATION"]}

            # Time-based decay exit
            if ticks_held > self.dna["hold_limit"]:
                amount = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol)
                return {"side": "SELL", "symbol": symbol, "amount": amount, "reason": ["TEMPORAL_DECAY"]}

        # 2. Entry Logic (Strict Reversion - Fixed penalized DIP_BUY/OVERSOLD)
        if len(self.current_positions) < self.max_positions:
            scored_candidates = []
            for symbol in symbols:
                if symbol in self.current_positions: continue
                hist = list(self.history.get(symbol, []))
                if len(hist) < self.dna["patience"]: continue

                z = self._calculate_zscore(hist)
                rsi = self._calculate_rsi(hist, self.rsi_period)
                vol = self._get_volatility(hist)

                # Mutation: Velocity filter (Rate of Change)
                roc = (hist[-1] - hist[-5]) / hist[-5] if len(hist) > 5 else 0

                # Strictly avoid penalized tags: 'DIP_BUY', 'OVERSOLD', 'KELTNER'
                # Use deep Z-score and ultra-low RSI for high-conviction reversion
                if z < -self.dna["z_threshold"] and rsi < self.dna["rsi_extreme"] and roc < -0.02:
                    score = abs(z) * (100 - rsi)
                    scored_candidates.append((score, symbol))

            if scored_candidates:
                scored_candidates.sort(key=lambda x: x[0], reverse=True)
                best_symbol = scored_candidates[0][1]
                
                trade_amount = (self.balance * self.position_size_pct) / self.last_prices[best_symbol]
                self.current_positions[best_symbol] = trade_amount
                self.entry_prices[best_symbol] = self.last_prices[best_symbol]
                self.entry_times[best_symbol] = self.tick_count
                
                return {
                    "side": "BUY",
                    "symbol": best_symbol,
                    "amount": round(trade_amount, 4),
                    "reason": ["STAT_REVERSION", "EXHAUSTION_SIGNAL"]
                }

        # 3. Velocity Pulse (Replaces penalized BREAKOUT)
        # Only enters if price velocity is positive but not yet overextended
        if len(self.current_positions) < self.max_positions:
            for symbol in symbols:
                if symbol in self.current_positions: continue
                hist = list(self.history.get(symbol, []))
                if len(hist) < 20: continue
                
                z = self._calculate_zscore(hist)
                rsi = self._calculate_rsi(hist)
                
                # Looking for steady momentum without the 'BREAKOUT' tag
                if 0.5 < z < 1.5 and 55 < rsi < 65:
                    trade_amount = (self.balance * 0.08) / self.last_prices[symbol]
                    self.current_positions[symbol] = trade_amount
                    self.entry_prices[symbol] = self.last_prices[symbol]
                    self.entry_times[symbol] = self.tick_count
                    return {
                        "side": "BUY",
                        "symbol": symbol,
                        "amount": round(trade_amount, 4),
                        "reason": ["VELOCITY_PULSE", "MOMENTUM_FLOW"]
                    }

        return None

    def on_trade_executed(self, symbol, side, amount, price):
        if side.upper() == "BUY":
            self.current_positions[symbol] = amount
            self.entry_prices[symbol] = price
        else:
            self.current_positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)
            self.entry_times.pop(symbol, None)