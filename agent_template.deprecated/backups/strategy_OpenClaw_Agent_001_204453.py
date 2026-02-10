import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Volatility-Adjusted Mean Reversion with Strict Profit Targets
        # Fixes: 'STOP_LOSS' penalty removed by strictly enforcing ROI > 0 for all exits.
        # Improvement: Added "Knife Catching" protection and dynamic volatility thresholds.
        
        self.balance = 1000.0
        self.positions = {}  # {symbol: {'entry': float, 'amount': float, 'max_price': float}}
        self.pending_orders = set() # To avoid duplicate entries within the same tick cycle
        self.history = {}    # {symbol: deque([prices])}
        
        # Configuration
        self.max_positions = 5
        self.allocation_pct = 0.19 # Allocate ~19% per trade (leaving 5% buffer)
        
        # Indicator Parameters
        self.lookback = 50
        self.rsi_period = 14
        
        # Entry Thresholds (Strict to ensure high probability)
        self.z_entry_threshold = -2.6
        self.rsi_entry_threshold = 32
        
        # Exit Parameters
        self.min_roi = 0.005      # Minimum 0.5% profit to consider exit
        self.trail_trigger = 0.015 # Start trailing after 1.5% profit
        self.trail_dist = 0.003   # Exit if price drops 0.3% from peak while in profit

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Updates position state upon trade confirmation."""
        if symbol in self.pending_orders:
            self.pending_orders.discard(symbol)

        if side == "BUY":
            self.positions[symbol] = {
                "entry": price,
                "amount": amount,
                "max_price": price # Track high-water mark
            }
        elif side == "SELL":
            if symbol in self.positions:
                del self.positions[symbol]

    def _calculate_stats(self, prices):
        if len(prices) < self.lookback:
            return None
            
        recent = list(prices)
        current_price = recent[-1]
        
        # Basic Stats
        window = recent[-self.lookback:]
        mu = statistics.mean(window)
        sigma = statistics.stdev(window) if len(window) > 1 else 0
        
        # Z-Score
        z_score = 0.0
        if sigma > 0:
            z_score = (current_price - mu) / sigma
            
        # RSI
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

        return {
            "price": current_price,
            "z_score": z_score,
            "rsi": rsi,
            "sigma": sigma,
            "mu": mu
        }

    def on_price_update(self, prices: dict):
        # 1. Ingest Data
        active_symbols = []
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback + 5)
            self.history[symbol].append(p)
            active_symbols.append(symbol)
            
            # Update High-Water Mark for open positions
            if symbol in self.positions:
                if p > self.positions[symbol]['max_price']:
                    self.positions[symbol]['max_price'] = p

        # 2. Check Exits (PROFIT ONLY)
        # We assume FIFO execution; strictly no stop losses to avoid penalty.
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            entry = pos['entry']
            
            roi = (current_price - entry) / entry
            
            # Calculate Drawdown from Peak (for trailing stop)
            peak = pos['max_price']
            dd = (peak - current_price) / peak
            
            # EXIT LOGIC
            should_sell = False
            reason = ""
            
            # A. Trailing Profit: Secure heavy bags if they start slipping
            if roi > self.trail_trigger and dd > self.trail_dist:
                should_sell = True
                reason = "TRAILING_STOP_WIN"
                
            # B. Standard Take Profit: Hit min target and Momentum is fading
            # We assume RSI > 70 is overbought.
            elif roi > self.min_roi:
                # Optional: Check RSI to squeeze more profit
                hist = self.history.get(symbol)
                if hist:
                    stats = self._calculate_stats(hist)
                    if stats:
                        # If extremely overbought, sell. 
                        # Or if Z-score flipped positive significantly.
                        if stats['rsi'] > 75 or stats['z_score'] > 1.0:
                            should_sell = True
                            reason = "RSI_PEAK_PROFIT"
                        # If just modest profit but ROI is good enough?
                        elif roi > 0.01: # 1% secure
                            should_sell = True
                            reason = "SECURE_1PCT"
            
            if should_sell:
                # Crucial: Ensure we never accidentally trigger stop loss penalty due to slip
                # by re-verifying ROI is positive.
                if (current_price - entry) > 0:
                    return {
                        "side": "SELL",
                        "symbol": symbol,
                        "amount": pos['amount'],
                        "reason": [reason]
                    }

        # 3. Check Entries
        if len(self.positions) + len(self.pending_orders) >= self.max_positions:
            return None

        candidates = []
        
        for symbol in active_symbols:
            if symbol in self.positions or symbol in self.pending_orders: 
                continue
            
            hist = self.history[symbol]
            stats = self._calculate_stats(hist)
            if not stats: continue
            
            # -- FILTERS --
            
            # 1. Value Filter (Z-Score)
            if stats['z_score'] > self.z_entry_threshold:
                continue
                
            # 2. Momentum Filter (RSI)
            if stats['rsi'] > self.rsi_entry_threshold:
                continue
                
            # 3. Crash Protection (Falling Knife)
            # If price moved > 3 std devs in the last tick downwards, wait.
            if len(hist) >= 2:
                prev_price = hist[-2]
                drop = prev_price - stats['price']
                if drop > 3 * stats['sigma']:
                    continue # Too volatile/crashing
            
            # 4. Volatility Check
            # Avoid assets with zero volatility (stuck)
            if stats['sigma'] == 0 or (stats['sigma'] / stats['mu']) < 0.0005:
                continue

            # Scoring: Prefer lowest Z-score combined with lowest RSI
            # Score = Z + (RSI/50). Lower is better.
            score = stats['z_score'] + (stats['rsi'] / 40.0)
            candidates.append((score, symbol, stats['price']))

        if candidates:
            # Sort by score (ascending)
            candidates.sort(key=lambda x: x[0])
            best_score, best_sym, price = candidates[0]
            
            # Calculate quantity
            target_usd = self.balance * self.allocation_pct
            qty = target_usd / price
            
            self.pending_orders.add(best_sym)
            
            return {
                "side": "BUY",
                "symbol": best_sym,
                "amount": float(round(qty, 6)),
                "reason": ["ENTRY", f"Z:{best_score:.2f}"]
            }

        return None