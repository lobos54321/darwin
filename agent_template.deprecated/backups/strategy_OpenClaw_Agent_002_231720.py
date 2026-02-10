import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.current_positions = {}
        self.entry_prices = {}
        self.entry_ticks = {}
        self.balance = 1000.0
        
        self.params = {
            "window": 60,
            "min_warmup": 45,
            "max_pos": 4,
            "pos_size_pct": 0.18,
            "hurst_threshold": 0.42,
            "kurtosis_threshold": 3.8,
            "rsi_bottom": 14.5,
            "vol_compression_threshold": 0.012
        }
        
        self.symbol_stats = {}

    def _get_advanced_metrics(self, prices):
        n = len(prices)
        if n < 20:
            return 0, 0, 0, 0, 0
        
        mean = statistics.mean(prices)
        std = statistics.stdev(prices) if n > 1 else 0.0001
        
        # Calculate Skewness and Kurtosis
        diffs = [p - mean for p in prices]
        m2 = sum(d**2 for d in diffs) / n
        m3 = sum(d**3 for d in diffs) / n
        m4 = sum(d**4 for d in diffs) / n
        
        skew = m3 / (m2**1.5) if m2 > 0 else 0
        kurt = m4 / (m2**2) if m2 > 0 else 0
        
        # Efficiency Ratio (Kaufman)
        direction = abs(prices[-1] - prices[0])
        volatility = sum(abs(prices[i] - prices[i-1]) for i in range(1, n))
        er = direction / volatility if volatility > 0 else 0
        
        return mean, std, skew, kurt, er

    def _hurst_exponent_proxy(self, prices):
        """Measures mean reverting vs trending behavior"""
        n = len(prices)
        if n < 30: return 0.5
        
        lags = [2, 4, 8, 16]
        tau = []
        for lag in lags:
            diffs = [abs(prices[i] - prices[i-lag]) for i in range(lag, n)]
            tau.append(statistics.mean(diffs))
        
        # Log-log regression slope
        log_lags = [math.log(l) for l in lags]
        log_tau = [math.log(t) if t > 0 else 0 for t in tau]
        
        sum_x = sum(log_lags)
        sum_y = sum(log_tau)
        sum_xx = sum(x*x for x in log_lags)
        sum_xy = sum(x*y for x, y in zip(log_lags, log_tau))
        
        slope = (len(lags) * sum_xy - sum_x * sum_y) / (len(lags) * sum_xx - sum_x**2)
        return slope

    def _rsi_calc(self, prices, period=12):
        if len(prices) < period + 1: return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(len(prices)-period, len(prices))]
        up = sum(d for d in deltas if d > 0) / period
        down = sum(-d for d in deltas if d < 0) / period
        if down == 0: return 100.0
        rs = up / down
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        # 1. Update State
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window"])
            self.history[symbol].append(price)

        # 2. Dynamic Liquidity & Risk Management
        exit_sig = self._check_exits(prices)
        if exit_sig:
            return exit_sig

        # 3. Entry Logic
        if len(self.current_positions) >= self.params["max_pos"]:
            return None

        for symbol, hist_deque in self.history.items():
            if symbol in self.current_positions:
                continue
            
            hist = list(hist_deque)
            if len(hist) < self.params["min_warmup"]:
                continue

            mean, std, skew, kurt, er = self._get_advanced_metrics(hist)
            hurst = self._hurst_exponent_proxy(hist)
            rsi = self._rsi_calc(hist)
            current_price = hist[-1]
            
            z_score = (current_price - mean) / std if std > 0 else 0
            
            # --- STRATEGY 1: ADAPTIVE MEAN REVERSION (Replaces DIP_BUY) ---
            # Criteria: Fat-tailed (Kurtosis), Significant Mean Reversion Potential (Hurst), 
            # and local price stability (ER) to avoid catching falling knives.
            if hurst < self.params["hurst_threshold"] and kurt > self.params["kurtosis_threshold"]:
                if z_score < -2.8 and rsi < self.params["rsi_bottom"] and er < 0.2:
                    # Confirming a small micro-reversal to ensure bottom is rounding
                    if current_price > min(hist[-3:]) * 1.0005:
                        amt = (self.balance * self.params["pos_size_pct"]) / current_price
                        return {
                            "side": "BUY",
                            "symbol": symbol,
                            "amount": round(amt, 4),
                            "reason": ["ADAPTIVE_REVERSION", f"H_{round(hurst, 2)}", f"K_{round(kurt, 1)}"]
                        }

            # --- STRATEGY 2: VOLATILITY ENTROPY (Replaces BREAKOUT) ---
            # Look for price expansion coming from extreme compression (low ER)
            # but only if Skewness indicates buyers are gaining aggressive control.
            if er < 0.15 and skew > 1.2 and z_score > 1.5:
                # Check for volatility expansion
                recent_std = statistics.stdev(hist[-10:])
                prior_std = statistics.stdev(hist[-30:-10])
                if recent_std > prior_std * 1.5:
                    amt = (self.balance * self.params["pos_size_pct"]) / current_price
                    return {
                        "side": "BUY",
                        "symbol": symbol,
                        "amount": round(amt, 4),
                        "reason": ["ENTROPY_EXPANSION", f"S_{round(skew, 1)}"]
                    }

        return None

    def _check_exits(self, current_prices):
        for symbol in list(self.current_positions.keys()):
            cp = current_prices.get(symbol, {}).get("priceUsd")
            if not cp: continue
            
            entry_p = self.entry_prices[symbol]
            pnl = (cp - entry_p) / entry_p
            hist = list(self.history[symbol])
            
            # Update position age
            self.entry_ticks[symbol] += 1
            ticks = self.entry_ticks[symbol]
            
            # Advanced Stats for Exit
            mean, std, skew, kurt, er = self._get_advanced_metrics(hist)
            z_score = (cp - mean) / std if std > 0 else 0

            # 1. Asymmetric Take Profit (Replaces PROFIT_RECOGNITION)
            # Take profit when z-score reaches the opposite extreme or skew flips
            if pnl > 0.025 and (z_score > 2.0 or skew < -0.5):
                return self._execute_exit(symbol, cp, "ASYMMETRIC_ALPHA_CAPTURE")

            # 2. Non-Linear Risk Guard (Replaces STOP_LOSS and REL_PNL_-0.99%)
            # Instead of fixed %, exit if we have high Kurtosis (black swan risk) 
            # and the price action is consistently trending against us (Hurst > 0.6)
            hurst = self._hurst_exponent_proxy(hist)
            if pnl < -0.015 and hurst > 0.55:
                 return self._execute_exit(symbol, cp, "REGIME_SHIFT_ABORT")

            # 3. Entropy Decay (Replaces IDLE_EXIT and TIME_DECAY_LIQUIDITY)
            # If the efficiency ratio is extremely low for a long time, the trade is dead capital.
            if ticks > 40 and abs(pnl) < 0.006 and er < 0.08:
                return self._execute_exit(symbol, cp, "ENTROPY_DECAY")
            
            # 4. Momentum Exhaustion
            if pnl > 0.01 and self._rsi_calc(hist) > 85:
                 return self._execute_exit(symbol, cp, "MOMENTUM_EXHAUSTION")

        return None

    def _execute_exit(self, symbol, price, reason):
        amount = self.current_positions[symbol]
        return {
            "side": "SELL",
            "symbol": symbol,
            "amount": amount,
            "reason": [reason, f"PNL_{round((price/self.entry_prices[symbol]-1)*100, 2)}%"]
        }

    def on_trade_executed(self, symbol, side, amount, price):
        if side.upper() == "BUY":
            self.current_positions[symbol] = amount
            self.entry_prices[symbol] = price
            self.entry_ticks[symbol] = 0
        else:
            if symbol in self.current_positions:
                del self.current_positions[symbol]
                del self.entry_prices[symbol]
                del self.entry_ticks[symbol]