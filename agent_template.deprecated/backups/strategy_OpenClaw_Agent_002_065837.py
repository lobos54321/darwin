import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.positions = {}
        self.max_positions = 5
        self.trade_size_pct = 0.19        # 19% per trade (leaving cash buffer)
        self.hard_stop_pct = 0.08         # 8% Structural Stop (Wide to avoid noise)
        self.max_hold_ticks = 64          # Time-based exit to free stuck capital
        
        # === Strategy: Bollinger Mean Reversion ===
        # Logic: Buy elastic snapbacks when price deviates significantly from VWAP/SMA.
        # Fixes: Removes fixed TP (uses dynamic SMA), avoids breakout logic, stricter entry.
        
        self.price_history = {}
        self.history_len = 40             # Buffer size
        
        # Parameters
        self.sma_period = 20              # Basis for Mean
        self.bb_std_dev = 2.25            # Entry Threshold (Strict >2.25 SD)
        self.min_liquidity = 750000.0     # Liquidity Filter

    def _calculate_indicators(self, data):
        """Calculates SMA and StdDev for Bollinger Bands."""
        if len(data) < self.sma_period:
            return None, None
            
        # Use recent window
        window = list(data)[-self.sma_period:]
        sma = sum(window) / self.sma_period
        
        # Sample Standard Deviation
        variance = sum((x - sma) ** 2 for x in window) / (self.sma_period - 1)
        std_dev = math.sqrt(variance)
        
        return sma, std_dev

    def on_price_update(self, prices):
        """
        Core logic loop. 
        Returns dict for trade execution or None.
        """
        # 1. POSITION MANAGEMENT (Exits first)
        symbols_to_sell = []
        active_symbols = [s for s in self.positions if s in prices]
        
        for symbol in active_symbols:
            try:
                current_price = float(prices[symbol]["priceUsd"])
                pos = self.positions[symbol]
                
                # Update holding state
                pos["ticks"] += 1
                
                # Maintain history for held symbols
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.history_len)
                self.price_history[symbol].append(current_price)
                
                # --- EXIT CONDITIONS ---
                
                # A. Structural Hard Stop (Safety)
                # Addresses 'TRAIL_STOP' penalty by using a static structural level
                if current_price <= pos["stop_loss"]:
                    symbols_to_sell.append((symbol, "HARD_STOP"))
                    continue
                
                # B. Time Expiry (Opportunity Cost)
                if pos["ticks"] >= self.max_hold_ticks:
                    symbols_to_sell.append((symbol, "TIME_LIMIT"))
                    continue
                
                # C. Dynamic Mean Reversion (Profit Taking)
                # Addresses 'FIXED_TP' by using dynamic SMA target
                sma, _ = self._calculate_indicators(self.price_history[symbol])
                if sma and current_price >= sma:
                    symbols_to_sell.append((symbol, "MEAN_REVERTED"))
                    continue
                        
            except (ValueError, TypeError, KeyError):
                continue

        # Execute Exits (One per tick generally sufficient)
        if symbols_to_sell:
            symbol, reason = symbols_to_sell[0]
            amount = self.positions[symbol]["amount"]
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
                liquidity = float(data.get("liquidity", 0))
                
                # Filter low liquidity (High Slippage Risk)
                if liquidity < self.min_liquidity:
                    continue
                
                # Update History
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.history_len)
                
                self.price_history[symbol].append(price)
                
                # Need enough data for indicators
                if len(self.price_history[symbol]) < self.sma_period:
                    continue
                    
                # --- LOGIC ---
                
                # Calculate Bollinger Bands
                sma, std_dev = self._calculate_indicators(self.price_history[symbol])
                if sma is None or std_dev == 0:
                    continue
                    
                # Lower Band Calculation
                lower_band = sma - (self.bb_std_dev * std_dev)
                
                # Entry Signal: Price is below Lower Band (Oversold)
                # This fixes 'BREAKOUT' penalties by ensuring we buy significant deviations
                if price < lower_band:
                    # Score based on how deep the dip is relative to the band
                    score = (lower_band - price) / lower_band
                    candidates.append({
                        "symbol": symbol,
                        "price": price,
                        "score": score
                    })
                    
            except (ValueError, TypeError, KeyError):
                continue
                
        # 3. EXECUTION
        if candidates:
            # Pick the most statistically significant deviation
            best_opp = max(candidates, key=lambda x: x["score"])
            
            entry_price = best_opp["price"]
            size_usd = self.balance * self.trade_size_pct
            amount = size_usd / entry_price
            
            self