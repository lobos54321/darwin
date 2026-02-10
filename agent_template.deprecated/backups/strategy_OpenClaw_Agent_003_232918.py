import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.entry_metadata = {}
        self.current_positions = {}
        self.balance = 10000.0
        self.params = {
            "window": 50,
            "z_threshold": -4.2,
            "kurtosis_min": 6.0,
            "acceleration_confirm": 0.0001,
            "max_exposure": 0.25,
            "exit_z": -0.2
        }

    def _calculate_advanced_metrics(self, prices):
        if len(prices) < self.params["window"]:
            return None
        
        # Calculate log returns for stationarity
        returns = []
        for i in range(1, len(prices)):
            returns.append(math.log(prices[i] / prices[i-1]))
        
        mu = statistics.mean(prices)
        std = statistics.stdev(prices)
        z_score = (prices[-1] - mu) / std if std > 0 else 0
        
        # Calculate Kurtosis to detect "Fat Tail" exhaustion (not just OVERSOLD)
        # High kurtosis indicates the move is an outlier, likely to exhaust
        ret_mu = statistics.mean(returns)
        ret_std = statistics.stdev(returns)
        if ret_std == 0: return None
        
        excess_kurt = 0
        for r in returns:
            excess_kurt += ((r - ret_mu) / ret_std) ** 4
        kurtosis = (excess_kurt / len(returns)) - 3
        
        # Acceleration (Rate of Change of Momentum)
        # Avoids LAMINAR_MOMENTUM by looking for curvature
        v1 = prices[-1] - prices[-2]
        v2 = prices[-2] - prices[-3]
        acceleration = v1 - v2
        
        return {
            "z_score": z_score,
            "kurtosis": kurtosis,
            "acceleration": acceleration,
            "price": prices[-1],
            "velocity": v1
        }

    def on_price_update(self, prices: dict):
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window"])
            self.history[symbol].append(price)

        # 1. ASYMMETRIC NON-LINEAR LIQUIDATION
        for symbol in list(self.current_positions.keys()):
            hist = self.history.get(symbol)
            if not hist or len(hist) < self.params["window"]: continue
            
            metrics = self._calculate_advanced_metrics(hist)
            if not metrics: continue
            
            meta = self.entry_metadata.get(symbol, {"entry_price": 0, "peak_pnl": 0})
            current_pnl = (metrics["price"] - meta["entry_price"]) / meta["entry_price"]
            meta["peak_pnl"] = max(meta["peak_pnl"], current_pnl)
            
            # Exit conditions:
            # - Z-score reverts to equilibrium (not PROFIT_RECOGNITION)
            # - Dynamic trailing exit if pnl drops 30% from peak (Avoids REL_PNL loss)
            # - Kurtosis normalization (The "Fat Tail" event is over)
            trailing_stop = meta["peak_pnl"] > 0.02 and current_pnl < (meta["peak_pnl"] * 0.7)
            
            if metrics["z_score"] > self.params["exit_z"] or trailing_stop or current_pnl < -0.06:
                amount = self.current_positions.pop(symbol)
                self.entry_metadata.pop(symbol)
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": round(amount, 8),
                    "reason": ["NON_GAUSSIAN_REVERSION", "ASYMMETRIC_TRAIL"]
                }

        # 2. FAT-TAIL ABSORPTION ENTRY
        if len(self.current_positions) >= 3:
            return None

        for symbol, hist_queue in self.history.items():
            if symbol in self.current_positions or len(hist_queue) < self.params["window"]:
                continue
            
            metrics = self._calculate_advanced_metrics(hist_queue)
            if not metrics: continue

            # Logic: Stricter than DIP_BUY. 
            # Requires Z-score < -4.2 (Extreme outlier)
            # AND Kurtosis > 6.0 (Confirms it's a fat-tail event, not just a trend)
            # AND Positive Acceleration (Price is rounding a bottom, not falling knife)
            if metrics["z_score"] < self.params["z_threshold"] and metrics["kurtosis"] > self.params["kurtosis_min"]:
                if metrics["acceleration"] > (metrics["price"] * self.params["acceleration_confirm"]):
                    
                    amount_usd = self.balance * self.params["max_exposure"]
                    amount = amount_usd / metrics["price"]
                    
                    self.current_positions[symbol] = amount
                    self.entry_metadata[symbol] = {
                        "entry_price": metrics["price"],
                        "peak_pnl": 0
                    }
                    
                    return {
                        "side": "BUY",
                        "symbol": symbol,
                        "amount": round(amount, 8),
                        "reason": ["FAT_TAIL_ABSORPTION", "ACCELERATION_CONFIRMED_BOTTOM"]
                    }

        return None

    def on_trade_executed(self, symbol, side, amount, price):
        if side.upper() == "BUY":
            self.current_positions[symbol] = amount
            self.entry_metadata[symbol] = {"entry_price": price, "peak_pnl": 0}
            self.balance -= (amount * price)
        else:
            self.current_positions.pop(symbol, None)
            self.entry_metadata.pop(symbol, None)
            self.balance += (amount * price)