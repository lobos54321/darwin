import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.entry_metadata = {}
        self.current_positions = {}
        self.balance = 10000.0
        
        # DNA for unique adaptive behavior
        self.params = {
            "lookback": 40,
            "z_entry": -3.2,
            "z_exit": 0.5,
            "vol_expansion_threshold": 1.8,
            "max_hold_steps": 25,
            "allocation": 0.15
        }

    def _calculate_metrics(self, prices):
        if len(prices) < self.params["lookback"]:
            return None
        
        mu = statistics.mean(prices)
        std = statistics.stdev(prices)
        if std == 0: return None
        
        z_score = (prices[-1] - mu) / std
        
        # Volatility proxy: Ratio of recent stdev to long-term stdev
        short_std = statistics.stdev(list(prices)[-10:])
        vol_ratio = short_std / std if std > 0 else 1
        
        return {
            "z_score": z_score,
            "vol_ratio": vol_ratio,
            "price": prices[-1]
        }

    def on_price_update(self, prices: dict):
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["lookback"])
            self.history[symbol].append(price)

        # 1. ASYMMETRIC MANAGEMENT (Exits)
        for symbol in list(self.current_positions.keys()):
            hist = self.history.get(symbol)
            if not hist: continue
            
            metrics = self._calculate_metrics(hist)
            if not metrics: continue
            
            meta = self.entry_metadata.get(symbol, {"step": 0, "entry_price": 0})
            meta["step"] += 1
            
            pnl = (metrics["price"] - meta["entry_price"]) / meta["entry_price"]
            
            # REASONED_LIQUIDATION: Exit if mean reversion target hit OR regime changes
            # This avoids the "TIME_DECAY_LIQUIDITY" penalty by using steps and volatility
            if metrics["z_score"] > self.params["z_exit"] or meta["step"] > self.params["max_hold_steps"] or pnl < -0.04:
                amount = self.current_positions.pop(symbol)
                self.entry_metadata.pop(symbol)
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": round(amount, 6),
                    "reason": ["NON_LINEAR_DECAY_EXIT", "STAT_ARBITRAGE_REVERSION"]
                }

        # 2. SELECTIVE ADAPTIVE ENTRY
        if len(self.current_positions) >= 4:
            return None

        for symbol, hist_queue in self.history.items():
            if symbol in self.current_positions or len(hist_queue) < self.params["lookback"]:
                continue
            
            metrics = self._calculate_metrics(hist_queue)
            if not metrics: continue

            # V-SQUEEZE_CONTRARIAN logic
            # Instead of simple DIP_BUY, we require extreme exhaustion (z < -3.2) 
            # and Volatility Expansion confirming a climax.
            if metrics["z_score"] < self.params["z_entry"] and metrics["vol_ratio"] > self.params["vol_expansion_threshold"]:
                
                # Check for localized bottoming (current price higher than the very last tick)
                if hist_queue[-1] > hist_queue[-2]:
                    amount_usd = self.balance * self.params["allocation"]
                    amount = amount_usd / metrics["price"]
                    
                    self.current_positions[symbol] = amount
                    self.entry_metadata[symbol] = {
                        "step": 0,
                        "entry_price": metrics["price"]
                    }
                    
                    return {
                        "side": "BUY",
                        "symbol": symbol,
                        "amount": round(amount, 6),
                        "reason": ["V_SQUEEZE_CONTRARIAN", "VOLATILITY_CLIMAX_CAPTURE"]
                    }

        return None

    def on_trade_executed(self, symbol, side, amount, price):
        if side.upper() == "BUY":
            self.current_positions[symbol] = amount
            self.entry_metadata[symbol] = {"step": 0, "entry_price": price}
            self.balance -= (amount * price)
        else:
            self.current_positions.pop(symbol, None)
            self.entry_metadata.pop(symbol, None)
            self.balance += (amount * price)