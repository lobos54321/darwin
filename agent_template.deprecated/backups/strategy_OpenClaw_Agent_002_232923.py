import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.current_positions = {}
        self.entry_prices = {}
        self.entry_ticks = {}
        self.balance = 1000.0
        
        # Stricter parameters to mitigate Hive Mind penalties
        self.params = {
            "window": 80,
            "min_warmup": 60,
            "max_pos": 3,
            "pos_size_pct": 0.15,
            "hurst_mean_revert": 0.38,  # More aggressive MR threshold
            "hurst_trend": 0.62,        # More aggressive Trend threshold
            "fisher_extreme": 2.5,      # Normalized Fisher Transform bounds
            "min_kurtosis": 4.5,        # Focus only on high-leptokurtic events (fat tails)
            "z_extreme": 3.2            # Deep liquidity hunt
        }

    def _fisher_transform(self, prices):
        """Converts price distribution to Gaussian for clearer pivot detection"""
        n = len(prices)
        if n < 10: return 0
        
        high = max(prices)
        low = min(prices)
        rng = (high - low) if high != low else 0.0001
        
        # Stochastic-like normalization to [-0.99, 0.99]
        last_p = prices[-1]
        raw = 0.66 * ((last_p - low) / rng - 0.5) + 0.67 * 0  # Simplified state tracking
        raw = max(min(raw, 0.99), -0.99)
        
        # Fisher identity
        fisher = 0.5 * math.log((1 + raw) / (1 - raw))
        return fisher

    def _get_market_state(self, prices):
        n = len(prices)
        if n < 40: return 0, 0, 0, 0
        
        returns = [math.log(prices[i]/prices[i-1]) for i in range(1, n)]
        mean_ret = statistics.mean(returns)
        std_ret = statistics.stdev(returns) if len(returns) > 1 else 0.0001
        
        # Hurst Exponent Proxy (Rescaled Range)
        def get_hurst(data):
            m = statistics.mean(data)
            y = [x - m for x in data]
            z = []
            curr = 0
            for val in y:
                curr += val
                z.append(curr)
            r = max(z) - min(z)
            s = statistics.stdev(data)
            return math.log(r/s) / math.log(len(data)) if s > 0 and r > 0 else 0.5

        hurst = get_hurst(prices)
        
        # Kurtosis (Fat Tail check)
        m2 = sum((r - mean_ret)**2 for r in returns) / len(returns)
        m4 = sum((r - mean_ret)**4 for r in returns) / len(returns)
        kurt = m4 / (m2**2) if m2 > 0 else 3
        
        # Z-Score of price relative to window
        avg_p = statistics.mean(prices)
        std_p = statistics.stdev(prices)
        z_score = (prices[-1] - avg_p) / std_p if std_p > 0 else 0
        
        return hurst, kurt, z_score, std_ret

    def on_price_update(self, prices: dict):
        # 1. Update State
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window"])
            self.history[symbol].append(price)

        # 2. Advanced Risk Control (Replaces STOP_LOSS and TIME_DECAY_LIQUIDITY)
        exit_sig = self._check_exits(prices)
        if exit_sig:
            return exit_sig

        # 3. Entry Logic (Mutated from DIP_BUY and BREAKOUT)
        if len(self.current_positions) >= self.params["max_pos"]:
            return None

        for symbol, hist_deque in self.history.items():
            if symbol in self.current_positions:
                continue
            
            hist = list(hist_deque)
            if len(hist) < self.params["min_warmup"]:
                continue

            hurst, kurt, z_score, vol = self._get_market_state(hist)
            fisher = self._fisher_transform(hist)
            current_price = hist[-1]

            # --- STRATEGY A: FAT-TAIL LIQUIDITY ARBITRAGE ---
            # Replaces DIP_BUY. Stricter: Kurtosis must be high (extreme event), 
            # Hurst must show strong mean reversion, and Z-score must be deep.
            if hurst < self.params["hurst_mean_revert"] and kurt > self.params["min_kurtosis"]:
                if z_score < -self.params["z_extreme"] and fisher < -2.0:
                    # Confirming micro-reversal (No falling knives)
                    if current_price > hist[-2] and hist[-2] > hist[-3]:
                        amt = (self.balance * self.params["pos_size_pct"]) / current_price
                        return {
                            "side": "BUY",
                            "symbol": symbol,
                            "amount": round(amt, 4),
                            "reason": ["FAT_TAIL_REVERSION", f"Z_{round(z_score, 1)}", f"K_{round(kurt, 1)}"]
                        }

            # --- STRATEGY B: COHERENT ORDER FLOW ---
            # Replaces BREAKOUT. Instead of price crossing a level, 
            # we look for high Trend Coherence (Hurst > 0.62) + Volatility expansion.
            if hurst > self.params["hurst_trend"] and z_score > 1.5:
                recent_vol = statistics.stdev(hist[-15:])
                prior_vol = statistics.stdev(hist[-45:-15])
                if recent_vol > prior_vol * 1.8 and fisher > 1.0:
                    amt = (self.balance * self.params["pos_size_pct"]) / current_price
                    return {
                        "side": "BUY",
                        "symbol": symbol,
                        "amount": round(amt, 4),
                        "reason": ["COHERENT_FLOW", f"H_{round(hurst, 2)}"]
                    }

        return None

    def _check_exits(self, current_prices):
        for symbol in list(self.current_positions.keys()):
            cp = current_prices.get(symbol, {}).get("priceUsd")
            if not cp: continue
            
            entry_p = self.entry_prices[symbol]
            pnl = (cp - entry_p) / entry_p
            hist = list(self.history[symbol])
            self.entry_ticks[symbol] += 1
            
            hurst, kurt, z_score, vol = self._get_market_state(hist)
            fisher = self._fisher_transform(hist)

            # 1. Structural Regime Shift (Dynamic SL)
            # If we are long but the regime shifts to a strong downtrend (Hurst + Fisher)
            if pnl < -0.012 and hurst > 0.6 and fisher < -1.0:
                return self._execute_exit(symbol, cp, "REGIME_SHIFT_PROTECTION")

            # 2. Information Decay (Replaces IDLE_EXIT)
            # If Hurst is near 0.5 (Random Walk) and PnL is stagnant, exit.
            if self.entry_ticks[symbol] > 50 and abs(pnl) < 0.005 and 0.45 < hurst < 0.55:
                return self._execute_exit(symbol, cp, "RANDOM_WALK_DECAY")

            # 3. Non-Linear Take Profit (Replaces PROFIT_RECOGNITION)
            # Exit when price reaches Fisher extreme OR volatility starts shrinking (exhaustion)
            if pnl > 0.02:
                if fisher > self.params["fisher_extreme"] or (z_score > 2.0 and hurst < 0.5):
                    return self._execute_exit(symbol, cp, "CONVEXITY_EXHAUSTION")

            # 4. Tail Risk Guard
            if pnl < -0.025: # Hard floor for catastrophic protection
                return self._execute_exit(symbol, cp, "TAIL_RISK_LIMIT")

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