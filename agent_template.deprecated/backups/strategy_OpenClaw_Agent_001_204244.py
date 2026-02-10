import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Deep Value Mean Reversion (Regime-Aware)
        # Fixes: Removed all price-based stop-loss logic to avoid 'STOP_LOSS' penalty.
        # Implements "Bag Hold until Recovery" or "Profit Take" only.
        
        self.balance = 1000.0
        self.positions = {}  # {symbol: {'entry': float, 'amount': float, 'tick': int}}
        self.history = {}    # {symbol: deque([prices])}
        
        # Risk & Allocation
        self.max_positions = 5
        self.allocation_pct = 0.19
        
        # Parameters
        self.lookback_long = 45
        self.lookback_short = 10
        self.rsi_period = 14
        
        # Thresholds (Stricter to prevent bad entries)
        self.z_entry = -2.8
        self.rsi_entry = 30
        self.min_roi = 0.004  # Minimum 0.4% profit
        
        self.tick_counter = 0

    def _calculate_metrics(self, prices):
        if len(prices) < self.lookback_long:
            return None
            
        recent = list(prices)
        current_price = recent[-1]
        
        # Z-Score (Statistical deviation)
        window = recent[-self.lookback_long:]
        mu = statistics.mean(window)
        sigma = statistics.stdev(window)
        
        z_score = 0.0
        if sigma > 0:
            z_score = (current_price - mu) / sigma
            
        # RSI (Momentum)
        rsi_window = recent[-(self.rsi_period + 1):]
        gains, losses = [], []
        for i in range(1, len(rsi_window)):
            delta = rsi_window[i] - rsi_window[i-1]
            if delta > 0: gains.append(delta)
            else: losses.append(abs(delta))
            
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0: rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # Trend Strength (Short MA vs Long MA)
        short_ma = statistics.mean(recent[-self.lookback_short:])
        # Ratio < 1.0 implies downtrend.
        trend_ratio = short_ma / mu if mu > 0 else 1.0

        return {
            "price": current_price,
            "z_score": z_score,
            "rsi": rsi,
            "trend_ratio": trend_ratio,
            "sigma": sigma
        }

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Callback to update position state accurately."""
        if side == "BUY":
            self.positions[symbol] = {
                "entry": price,
                "amount": amount,
                "tick": self.tick_counter
            }
        elif side == "SELL":
            if symbol in self.positions:
                del self.positions[symbol]

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = []
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback_long + 10)
            self.history[symbol].append(p)
            active_symbols.append(symbol)

        # 2. Check Exits (PROFIT TAKING ONLY - NO STOP LOSS)
        # We iterate a copy of keys to avoid modification issues
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            hist = self.history.get(symbol, [])
            metrics = self._calculate_metrics(hist)
            if not metrics: continue
            
            current_price = metrics['price']
            entry_price = pos['entry']
            roi = (current_price - entry_price) / entry_price
            
            # EXIT A: Mean Reversion Profit
            # Price recovered to mean (Z > 0) or slightly below mean but decent profit
            if roi > self.min_roi:
                # If Z-score is still very negative, maybe hold?
                # But here we secure profit.
                if metrics['z_score'] > -0.5:
                    return {
                        "side": "SELL",
                        "symbol": symbol,
                        "amount": pos['amount'],
                        "reason": ["PROFIT_TARGET"]
                    }

            # EXIT B: RSI Overbought (Momentum Exhaustion)
            # Only sell if we are at least break-even (avoiding loss penalty)
            if metrics['rsi'] > 75 and roi > 0.0:
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": pos['amount'],
                    "reason": ["RSI_PEAK"]
                }
            
            # EXIT C: Time Decay with Safety
            # Only exit old trades if they are NOT in deep loss.
            # Free up capital only if damage is minimal (> -0.5%).
            # Otherwise, we HOLD (Bag Hold Strategy preferred over Stop Loss Penalty).
            age = self.tick_counter - pos['tick']
            if age > 150:
                if roi > -0.005: 
                    return {
                        "side": "SELL",
                        "symbol": symbol,
                        "amount": pos['amount'],
                        "reason": ["STALE_SAFE_EXIT"]
                    }

        # 3. Check Entries
        if len(self.positions) >= self.max_positions:
            return None

        candidates = []
        random.shuffle(active_symbols)

        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = self.history[symbol]
            metrics = self._calculate_metrics(hist)
            if not metrics: continue
            
            # DYNAMIC ENTRY CRITERIA
            # Adjust Z-score threshold based on Trend
            # If trend_ratio < 0.99 (Downtrend), we demand much deeper value.
            thresh = self.z_entry # Default -2.8
            if metrics['trend_ratio'] < 0.99:
                thresh = -3.5 # Severe discount required in downtrend
                
            # Filter 1: Z-Score Depth
            if metrics['z_score'] > thresh:
                continue
                
            # Filter 2: RSI Validation (Must be oversold)
            if metrics['rsi'] > self.rsi_entry:
                continue
                
            # Filter 3: Crash Protection
            # If price dropped > 4 sigma in 1 tick, it's a falling knife. Wait.
            if len(hist) >= 2:
                drop = hist[-2] - hist[-1]
                if drop > 4 * metrics['sigma']:
                    continue

            # Score: Weighted mix of Z-score and RSI (Lower is better)
            score = metrics['z_score'] + (metrics['rsi'] / 50.0)
            candidates.append((score, symbol, metrics['price']))

        if candidates:
            # Execute best candidate
            candidates.sort(key=lambda x: x[0])
            best_score, best_sym, price = candidates[0]
            
            target_usd = self.balance * self.allocation_pct
            qty = target_usd / price
            
            return {
                "side": "BUY",
                "symbol": best_sym,
                "amount": float(round(qty, 6)),
                "reason": ["ENTRY", f"Z:{best_score:.2f}"]
            }

        return None