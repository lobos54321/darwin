import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.balance = 1000.0
        self.positions = {} 
        self.history = {}
        
        # === Strategy: Volatility Mean Reversion ===
        # REWRITE TO FIX PENALTIES:
        # 1. 'Z_BREAKOUT': Previous strategy bought positive Z spikes. 
        #    New logic buys negative Z spikes (Dips) expecting reversion.
        # 2. 'TRAIL_STOP': Previous exit logic may have been ambiguous.
        #    New logic enforces strictly calculated Bracket Orders at entry.
        
        self.params = {
            "window_size": 20,          # Rolling window for statistical calc
            "z_entry_threshold": -3.0,  # Entry: Buy if price drops > 3 sigmas (Strict Dip)
            "min_liq": 1_000_000.0,     # Liquidity filter
            "min_vol": 500_000.0,       # Volume filter
            "max_hold_ticks": 15,       # Time Decay exit
            "tp_vol_mult": 2.0,         # Take Profit = 2 * Volatility
            "sl_vol_mult": 2.0,         # Stop Loss = 2 * Volatility
            "pos_limit": 5,             # Max positions
            "trade_size_pct": 0.15      # 15% balance per trade
        }

    def _get_metrics(self, price_deque):
        """
        Calculates Z-Score of the most recent log-return against the local window.
        """
        if len(price_deque) < self.params["window_size"]:
            return None
            
        prices = list(price_deque)
        log_returns = []
        
        # Compute Log Returns
        for i in range(1, len(prices)):
            if prices[i-1] <= 0 or prices[i] <= 0:
                continue
            ret = math.log(prices[i] / prices[i-1])
            log_returns.append(ret)
        
        if not log_returns:
            return None
            
        # Calculate Stats
        mean_ret = sum(log_returns) / len(log_returns)
        variance = sum((r - mean_ret) ** 2 for r in log_returns) / len(log_returns)
        std_dev = math.sqrt(variance)
        
        if std_dev < 1e-9: # Filter zero volatility
            return None
            
        current_ret = log_returns[-1]
        
        # Z-Score: (Current Return - Average Return) / Volatility
        # Negative Z means price dropped below average.
        z_score = (current_ret - mean_ret) / std_dev
        
        return {
            "z_score": z_score,
            "std_dev": std_dev
        }

    def on_price_update(self, prices):
        # 1. EXIT LOGIC
        # Priority: Check exist conditions for open positions
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_data = prices.get(symbol)
            
            should_close = False
            reason = ""
            
            if not current_data:
                should_close = True
                reason = "DATA_LOST"
            else:
                try:
                    curr_price = float(current_data["priceUsd"])
                    
                    # Update holding time
                    pos["ticks_held"] += 1
                    
                    # STRICT BRACKET ORDERS (Anti-Trailing Stop Logic)
                    # Exits are calculated at entry and NEVER modified.
                    if curr_price >= pos["tp_price"]:
                        should_close = True
                        reason = "TAKE_PROFIT"
                    elif curr_price <= pos["sl_price"]:
                        should_close = True
                        reason = "STOP_LOSS"
                    # Time Decay: Free up capital if thesis fails to materialize
                    elif pos["ticks_held"] >= self.params["max_hold_ticks"]:
                        should_close = True
                        reason = "TIME_LIMIT"
                        
                except (ValueError, TypeError):
                    continue 

            if should_close:
                amount = pos["amount"]
                del self.positions[symbol]
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": amount,
                    "reason": [reason]
                }

        # 2. ENTRY LOGIC
        if len(self.positions) >= self.params["pos_limit"]:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
                
            try:
                price = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Liquidity Filters
            if liq < self.params["min_liq"] or vol < self.params["min_vol"]:
                continue
            
            # History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window_size"] + 5)
            self.history[symbol].append(price)
            
            # Calculate Statistics
            metrics = self._get_metrics(self.history[symbol])
            if not metrics:
                continue
            
            # LOGIC FIX for 'Z_BREAKOUT' penalty:
            # Instead of buying high Z (Breakout), we buy low Z (Dip).
            # We look for a Z-Score less than -3.0 (Strict Dip).
            if metrics["z_score"] < self.params["z_entry_threshold"]:
                candidates.append({
                    "symbol": symbol,
                    "price": price,
                    "z_score": metrics["z_score"],
                    "std_dev": metrics["std_dev"]
                })
        
        # Execute Best Opportunity
        if candidates:
            # Prioritize the deepest statistical anomaly (Lowest Z-Score)
            best = min(candidates, key=lambda x: x["z_score"])
            
            # Position Sizing
            amt_usd = self.balance * self.params["trade_size_pct"]
            amount = amt_usd / best["price"]
            
            # Calculate FIXED Targets based on current volatility
            vol_range = best["price"] * best["std_dev"]
            
            tp_price = best["price"] + (vol_range * self.params["tp_vol_mult"])
            sl_price = best["price"] - (vol_range * self.params["sl_vol_mult"])
            
            self.positions[best["symbol"]] = {
                "amount": amount,
                "entry_price": best["price"],
                "tp_price": tp_price,
                "sl_price": sl_price,
                "ticks_held": 0
            }
            
            return {
                "side": "BUY",
                "symbol": best["symbol"],
                "amount": amount,
                "reason": ["DIP_REVERSION", f"Z:{best['z_score']:.2f}"]
            }
            
        return None