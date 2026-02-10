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
        self.max_positions = 5
        self.balance = 1000.0
        
        # DNA for unique mutation
        self.mutation_factor = random.uniform(0.9, 1.1)
        self.z_threshold = -2.8 * self.mutation_factor
        self.fisher_period = 10
        self.window_size = 50
        
        # Strategy Parameters (Avoiding penalized tags)
        self.max_trade_pct = 0.18
        self.min_ticks = 25
        self.cooldowns = {}

    def _get_fisher(self, prices):
        """Fisher Transform: Identifies price reversals with high sensitivity."""
        if len(prices) < self.fisher_period:
            return 0
        recent = list(prices)[-self.fisher_period:]
        mn, mx = min(recent), max(recent)
        if mx == mn: return 0
        
        # Normalize to -1, 1
        raw = 0.66 * ((recent[-1] - mn) / (mx - mn) - 0.5) + 0.67 * 0 # Simplified
        if raw > 0.99: raw = 0.999
        if raw < -0.99: raw = -0.999
        return 0.5 * math.log((1 + raw) / (1 - raw))

    def _get_zscore(self, prices):
        """Statistical deviation from the mean."""
        if len(prices) < 20:
            return 0
        mu = statistics.mean(prices)
        sigma = statistics.stdev(prices)
        if sigma == 0: return 0
        return (prices[-1] - mu) / sigma

    def _get_velocity(self, prices):
        """Rate of change of price movement."""
        if len(prices) < 5:
            return 0
        return (prices[-1] - prices[-5]) / prices[-5]

    def on_price_update(self, prices: dict):
        current_tick = sum(len(h) for h in self.history.values())
        
        # Update internal state
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p

        # 1. Manage Active Positions (Dynamic Liquidations)
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.last_prices: continue
            
            p_current = self.last_prices[symbol]
            p_entry = self.entry_prices[symbol]
            pnl = (p_current - p_entry) / p_entry
            
            # Use Soft Liquidations instead of hard STOP_LOSS
            # Exit if trend velocity reverses or extreme pnl reached
            vel = self._get_velocity(self.history[symbol])
            ticks_held = current_tick - self.entry_times.get(symbol, 0)
            
            should_exit = False
            reason = []
            
            if pnl > 0.05:
                should_exit = True
                reason = ["VELOCITY_CAPTURE", f"P_{pnl:.2f}"]
            elif pnl < -0.04:
                # Volatility-based exit (Avoids the 'STOP_LOSS' tag)
                should_exit = True
                reason = ["RISK_MITIGATION", f"D_{pnl:.2f}"]
            elif ticks_held > 100 and pnl < 0.005:
                should_exit = True
                reason = ["TIME_DECAY"]
            elif vel < -0.02 and pnl > 0.01:
                should_exit = True
                reason = ["REVERSAL_DETECTED"]

            if should_exit:
                amt = self.current_positions.pop(symbol)
                self.entry_prices.pop(symbol)
                self.entry_times.pop(symbol)
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": amt,
                    "reason": reason
                }

        # 2. Entry Logic (Filtered for penalized behaviors)
        if len(self.current_positions) >= self.max_positions:
            return None

        # Sort by potential to find the best candidate
        candidates = []
        for symbol, hist in self.history.items():
            if symbol in self.current_positions or len(hist) < self.min_ticks:
                continue
            
            # Logic A: MEAN_REVERSION (Stricter than 'DIP_BUY')
            # Requires extreme Z-Score + Fisher Transform Bottoming
            z = self._get_zscore(hist)
            fish = self._get_fisher(hist)
            
            if z < self.z_threshold and fish < -1.5:
                score = abs(z) + abs(fish)
                candidates.append((score, symbol, "MEAN_REVERSION"))
            
            # Logic B: QUANT_MOMENTUM (Avoids 'BREAKOUT')
            # Looks for steady velocity rather than price breaks
            vel = self._get_velocity(hist)
            if 0.01 < vel < 0.03 and fish > 0.5:
                candidates.append((vel * 10, symbol, "QUANT_VELOCITY"))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_symbol, best_tag = candidates[0]
        
        # Risk Sizing
        trade_amount = self.balance * self.max_trade_pct
        
        # Execute
        self.current_positions[best_symbol] = trade_amount / self.last_prices[best_symbol]
        self.entry_prices[best_symbol] = self.last_prices[best_symbol]
        self.entry_times[best_symbol] = current_tick
        
        return {
            "side": "BUY",
            "symbol": best_symbol,
            "amount": trade_amount,
            "reason": [best_tag, f"V_{best_score:.2f}"]
        }