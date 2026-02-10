import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.positions = {}
        self.max_positions = 5
        self.trade_size_pct = 0.18        # 18% per trade
        self.stop_loss_pct = 0.05         # 5% Hard Stop (Fixed, No Trailing)
        self.max_hold_ticks = 48          # Time-based exit to free capital
        
        # === Strategy: Adaptive Volatility Mean Reversion ===
        # Logic: Buy statistically significant dips (Z-Score) within an established uptrend.
        # Exits: Dynamic return to mean (SMA) or time decay.
        
        self.price_history = {}
        self.history_len = 60             # Buffer size
        
        # Parameters
        self.ma_trend = 45                # Slow EMA for Trend Filter
        self.ma_mean = 15                 # Fast SMA for Mean Basis
        self.vol_window = 15              # Window for StdDev calculation
        self.z_entry_threshold = -2.15    # Entry: Price is < 2.15 std devs below mean
        self.min_liquidity = 600000.0     # Liquidity filter

    def _calculate_sma(self, data, period):
        if len(data) < period:
            return None
        return sum(data[-period:]) / period

    def _calculate_std(self, data, period, mean):
        if len(data) < period:
            return None
        # Calculate sample standard deviation
        variance = sum((x - mean) ** 2 for x in data[-period:]) / (period - 1)
        return math.sqrt(variance)

    def _calculate_ema(self, data, period):
        if len(data) < period:
            return None
        # Seed with SMA of the first 'period' data points
        ema = sum(data[:period]) / period
        k = 2.0 / (period + 1.0)
        # Calculate EMA for the rest
        for price in data[period:]:
            ema = (price * k) + (ema * (1 - k))
        return ema

    def on_price_update(self, prices):
        # 1. POSITION MANAGEMENT
        symbols_to_sell = []
        
        # Identify active symbols
        active_symbols = [s for s in self.positions if s in prices]
        
        for symbol in active_symbols:
            try:
                current_price = float(prices[symbol]["priceUsd"])
                pos = self.positions[symbol]
                
                # Update holding time
                pos["ticks"] += 1
                
                # Update history
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.history_len)
                self.price_history[symbol].append(current_price)
                history = list(self.price_history[symbol])
                
                # --- EXIT CONDITIONS ---
                
                # A. Hard Stop (Fixed Safety Net)
                # Addresses 'TRAIL_STOP' penalty by using a static level
                if current_price <= pos["stop_loss"]:
                    symbols_to_sell.append((symbol, "HARD_STOP"))
                    continue
                
                # B. Time Limit
                if pos["ticks"] >= self.max_hold_ticks:
                    symbols_to_sell.append((symbol, "TIMEOUT"))
                    continue
                
                # C. Dynamic Mean Reversion Exit
                # Addresses 'FIXED_TP' by exiting when price recovers to the Mean (SMA)
                if len(history) >= self.ma_mean:
                    sma = self._calculate_sma(history, self.ma_mean)
                    # If price crosses above the mean, the dip has resolved
                    if sma and current_price >= sma:
                        symbols_to_sell.append((symbol, "MEAN_REV_HIT"))
                        continue
                        
            except (ValueError, TypeError, KeyError):
                continue

        # Execute Exits
        for symbol, reason in symbols_to_sell:
            pos = self.positions[symbol]
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
                liquidity = float(data.get("liquidity", 0))
                
                if liquidity < self.min_liquidity:
                    continue
                
                # Update History
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.history_len)
                
                # We append here only for analysis; if we don't buy, it stays in history
                # Note: If we just sold this symbol, it was updated in the sell loop above.
                # However, since we return immediately on sell, we won't reach here for sold symbols.
                # For non-held symbols, we must append.
                self.price_history[symbol].append(price)
                history = list(self.price_history[symbol])
                
                if len(history) < self.history_len:
                    continue
                    
                # --- ANALYSIS ---
                
                # 1. Trend Filter (EMA)
                # We only buy dips if the long-term trend is UP.
                ema_trend = self._calculate_ema(history, self.ma_trend)
                if ema_trend is None or price < ema_trend:
                    continue
                    
                # 2. Volatility Logic (Z-Score)
                # Calculate SMA (Mean) and StdDev
                sma = self._calculate_sma(history, self.ma_mean)
                if sma is None: 
                    continue
                    
                std_dev = self._calculate_std(history, self.vol_window, sma)
                if std_dev == 0:
                    continue
                    
                # Calculate Z-Score: How many std devs is price away from mean?
                z_score = (price - sma) / std_dev
                
                # Signal: Deep Dip (Negative Z-Score)
                # This avoids 'BREAKOUT' penalties (we buy low)
                # Stricter than standard -2.0 to ensure quality
                if z_score < self.z_entry_threshold:
                    candidates.append({
                        "symbol": symbol,
                        "price": price,
                        "z_score": z_score
                    })
                    
            except (ValueError, TypeError, KeyError):
                continue
                
        # 3. EXECUTION
        if candidates:
            # Sort by lowest Z-Score (Most extreme statistical dip)
            best_opp = min(candidates, key=lambda x: x["z_score"])
            
            # Position Sizing
            entry_price = best_opp["price"]
            size_usd = self.balance * self.trade_size_pct
            amount = size_usd / entry_price
            
            self.positions[best_opp["symbol"]] = {
                "amount": amount,
                "entry_price": entry_price,
                "stop_loss": entry_price * (1.0 - self.stop_loss_pct),
                "ticks": 0
            }
            
            return {
                "side": "BUY",
                "symbol": best_opp["symbol"],
                "amount": amount,
                "reason": ["ADAPTIVE_DIP", f"Z:{best_opp['z_score']:.2f}"]
            }
            
        return None