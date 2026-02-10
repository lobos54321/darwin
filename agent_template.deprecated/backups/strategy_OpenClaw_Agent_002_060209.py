import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.balance = 1000.0
        self.positions = {}
        self.price_history = {}
        
        # === Configuration ===
        # REWRITE NOTES:
        # 1. Fixed 'Z_BREAKOUT' by using Bollinger Band Mean Reversion (Buy Low Z-Score).
        #    We calculate Z-Score of Price vs MA, not Returns, for a more stable signal.
        # 2. Fixed 'TRAIL_STOP' by implementing Immutable Bracket Orders calculated at entry.
        
        self.lookback = 30              # Window size for MA and Volatility
        self.z_buy_threshold = -2.2     # Entry: Price must be < -2.2 StdDevs (Deep Dip)
        self.min_liquidity = 500_000.0  # Liquidity Filter
        self.min_volume = 100_000.0     # Volume Filter
        self.max_hold_ticks = 25        # Time decay for stagnant trades
        self.max_positions = 5          # Diversity limit
        self.trade_size_pct = 0.18      # 18% balance per trade
        
        # Risk Settings (Fixed at Entry)
        self.tp_mult = 2.5              # Take Profit = 2.5x StdDev
        self.sl_mult = 3.0              # Stop Loss = 3.0x StdDev (Wide for volatility breathing room)

    def _get_bollinger_z(self, price_deque):
        """
        Calculates Z-Score of the current price relative to the moving average (Bollinger logic).
        Returns (z_score, std_dev).
        """
        if len(price_deque) < self.lookback:
            return None, None
            
        prices = list(price_deque)
        avg_price = sum(prices) / len(prices)
        
        variance = sum((p - avg_price) ** 2 for p in prices) / len(prices)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0:
            return None, None
            
        current_price = prices[-1]
        
        # Z-Score = (Price - Mean) / StdDev
        # Negative Z means price is below average (Oversold).
        z_score = (current_price - avg_price) / std_dev
        
        return z_score, std_dev

    def on_price_update(self, prices):
        # 1. EXIT MANAGEMENT (Strict Priority)
        # Iterate copy of keys to allow deletion
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            market_data = prices.get(symbol)
            
            should_close = False
            reason = ""
            
            if not market_data:
                should_close = True
                reason = "DATA_LOST"
            else:
                try:
                    current_price = float(market_data["priceUsd"])
                    pos["ticks_held"] += 1
                    
                    # IMMUTABLE BRACKET CHECKS (Anti-Trailing Stop)
                    # These values (tp_price, sl_price) are never updated after entry.
                    if current_price >= pos["tp_price"]:
                        should_close = True
                        reason = "TAKE_PROFIT"
                    elif current_price <= pos["sl_price"]:
                        should_close = True
                        reason = "STOP_LOSS"
                    elif pos["ticks_held"] >= self.max_hold_ticks:
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

        # 2. ENTRY SCANNING
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
                
            try:
                price = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                
                # Basic Filters
                if liq < self.min_liquidity or vol < self.min_volume:
                    continue
                
                # History Maintenance
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.lookback)
                self.price_history[symbol].append(price)
                
                # Statistical Calculation
                z_score, std_dev = self._get_bollinger_z(self.price_history[symbol])
                
                if z_score is None:
                    continue
                
                # MEAN REVERSION LOGIC
                # Buy only if price is significantly below the Moving Average.
                # Strictly avoids buying Breakouts (High Z).
                if z_score < self.z_buy_threshold:
                    candidates.append({
                        "symbol": symbol,
                        "price": price,
                        "z_score": z_score,
                        "std_dev": std_dev
                    })
                    
            except (ValueError, TypeError, KeyError):
                continue
        
        # 3. EXECUTION
        if candidates:
            # Select the deepest dip (Lowest Z-Score)
            best_opp = min(candidates, key=lambda x: x["z_score"])
            
            entry_price = best_opp["price"]
            amt_usd = self.balance * self.trade_size_pct
            amount = amt_usd / entry_price
            
            # Calculate FIXED Targets based on Volatility
            vol_range = best_opp["std_dev"]
            
            # Safety clamp for very low volatility assets to ensure spread coverage
            min_vol = entry_price * 0.002 # 0.2% minimum volatility assumption
            if vol_range < min_vol:
                vol_range = min_vol
                
            tp_price = entry_price + (vol_range * self.tp_mult)
            sl_price = entry_price - (vol_range * self.sl_mult)
            
            self.positions[best_opp["symbol"]] = {
                "amount": amount,
                "entry_price": entry_price,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "ticks_held": 0
            }
            
            return {
                "side": "BUY",
                "symbol": best_opp["symbol"],
                "amount": amount,
                "reason": ["MEAN_REVERSION", f"Z:{best_opp['z_score']:.2f}"]
            }
            
        return None