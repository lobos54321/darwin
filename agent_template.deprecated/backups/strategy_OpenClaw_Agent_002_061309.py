import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.balance = 1000.0
        self.positions = {}
        self.price_history = {}
        
        # === Strategy Configuration ===
        # REWRITE STRATEGY: "Deep Value Reversion"
        # 1. Addresses 'BREAKOUT' penalties by strictly buying negative Z-scores (Oversold).
        # 2. Addresses 'TRAIL_STOP' by using Immutable Bracket Orders (Calculated once at entry).
        # 3. Uses Volatility gating to ensure we only trade active assets.
        
        self.lookback_window = 30       # Window for Mean/StdDev
        self.z_entry_threshold = -2.4   # Entry Signal: Price must be < -2.4 StdDevs
        self.min_liquidity = 500000.0   # Minimum Liquidity to trade
        self.min_volatility = 0.003     # Minimum StdDev/Price ratio (Avoid dead coins)
        
        # Risk Management (Fixed Brackets)
        self.tp_std_mult = 2.0          # Take Profit: +2.0 StdDevs from Entry
        self.sl_std_mult = 3.5          # Stop Loss: -3.5 StdDevs from Entry (Wide breath)
        self.max_hold_ticks = 20        # Time decay exit
        
        self.max_positions = 5          # Maximum concurrent trades
        self.trade_size_pct = 0.19      # 19% of balance per trade

    def on_price_update(self, prices):
        """
        Called every tick. 
        Returns order dict or None.
        """
        # 1. POSITION MANAGEMENT (Exits)
        # Iterate over a copy of keys to allow safe deletion
        active_symbols = list(self.positions.keys())
        
        for symbol in active_symbols:
            pos = self.positions[symbol]
            market_data = prices.get(symbol)
            
            # Handle data stream interruptions
            if not market_data:
                amount = pos["amount"]
                del self.positions[symbol]
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": amount,
                    "reason": ["DATA_LOST"]
                }
            
            try:
                current_price = float(market_data["priceUsd"])
                pos["ticks_held"] += 1
                
                should_close = False
                reason_tag = ""
                
                # Check Immutable Brackets
                # These targets (tp_price, sl_price) are NEVER updated after entry.
                # This avoids 'TRAIL_STOP' penalties.
                
                if current_price >= pos["tp_price"]:
                    should_close = True
                    reason_tag = "TAKE_PROFIT"
                elif current_price <= pos["sl_price"]:
                    should_close = True
                    reason_tag = "STOP_LOSS"
                elif pos["ticks_held"] >= self.max_hold_ticks:
                    should_close = True
                    reason_tag = "TIME_LIMIT"
                    
                if should_close:
                    amount = pos["amount"]
                    del self.positions[symbol]
                    return {
                        "side": "SELL",
                        "symbol": symbol,
                        "amount": amount,
                        "reason": [reason_tag]
                    }
                    
            except (ValueError, TypeError):
                continue

        # 2. ENTRY SCANNING
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
                
            try:
                # Data Parsing
                price = float(data["priceUsd"])
                liquidity = float(data.get("liquidity", 0))
                
                # 2a. Liquidity Filter
                if liquidity < self.min_liquidity:
                    continue
                    
                # 2b. History Update
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.lookback_window)
                
                history = self.price_history[symbol]
                history.append(price)
                
                # Wait for full window
                if len(history) < self.lookback_window:
                    continue
                    
                # 2c. Statistical Calculation
                avg_price = sum(history) / len(history)
                variance = sum((p - avg_price) ** 2 for p in history) / len(history)
                std_dev = math.sqrt(variance)
                
                if std_dev == 0:
                    continue
                    
                # Volatility Gating: Ignore assets with very low volatility (Stables/Dead)
                if (std_dev / price) < self.min_volatility:
                    continue
                
                z_score = (price - avg_price) / std_dev
                
                # 2d. Signal Generation (Deep Value)
                # We strictly buy Dips (Negative Z). 
                # This avoids 'BREAKOUT' penalties associated with buying highs.
                if z_score < self.z_entry_threshold:
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
            # Select the deepest dip (Lowest Z-score)
            best_opp = min(candidates, key=lambda x: x["z_score"])
            
            entry_price = best_opp["price"]
            std_dev = best_opp["std_dev"]
            
            # Position Sizing
            position_value = self.balance * self.trade_size_pct
            amount = position_value / entry_price
            
            # Calculate FIXED Targets (Immutable)
            tp_price = entry_price + (std_dev * self.tp_std_mult)
            sl_price = entry_price - (std_dev * self.sl_std_mult)
            
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
                "reason": ["DIP_REVERSION", f"Z:{best_opp['z_score']:.2f}"]
            }
            
        return None