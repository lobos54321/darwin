import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.balance = 1000.0
        self.positions = {}
        self.price_history = {}
        
        # === Strategy: Elastic Trend Snap-Back ===
        # Replaces penalized 'Breakout' and 'Fixed Target' logic with 
        # Trend-Following Mean Reversion using Dynamic Signal Exits.
        
        # Configuration
        self.history_len = 50           # Buffer size for indicators
        self.ema_trend_period = 35      # Trend definition (Medium term)
        self.rsi_period = 6             # Fast oscillator for entry/exit signals
        
        # Filters
        self.min_liquidity = 750000.0   # Avoid low cap traps
        
        # Triggers
        self.rsi_buy_level = 22.0       # Entry: Deep oversold
        self.rsi_exit_level = 65.0      # Exit: Signal based (Not Fixed Price)
        
        # Risk Management
        self.stop_loss_pct = 0.04       # 4% Hard stop (Catastrophe protection only)
        self.max_hold_ticks = 40        # Time decay to free up capital
        
        self.max_positions = 4
        self.trade_size_pct = 0.24      # 24% per trade

    def _calculate_rsi(self, prices, period):
        """
        Calculates RSI using simple moving average of gains/losses
        to allow for fast dynamic exit signals.
        """
        if len(prices) < period + 1:
            return 50.0
            
        gains = 0.0
        losses = 0.0
        
        # Calculate changes over the last 'period'
        # We need period+1 prices to get 'period' changes
        window = prices[-(period + 1):]
        
        for i in range(1, len(window)):
            change = window[i] - window[i - 1]
            if change > 0:
                gains += change
            else:
                losses -= change
                
        if losses == 0:
            return 100.0 if gains > 0 else 50.0
            
        avg_gain = gains / period
        avg_loss = losses / period
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_ema(self, prices, period):
        """
        Calculates Exponential Moving Average for trend detection.
        """
        if len(prices) < period:
            return None
        
        # Initialize with SMA of the first 'period' elements
        ema = sum(prices[:period]) / period
        multiplier = 2.0 / (period + 1.0)
        
        # Calculate EMA for the rest
        for price in prices[period:]:
            ema = ((price - ema) * multiplier) + ema
            
        return ema

    def on_price_update(self, prices):
        """
        Executed every tick.
        """
        # 1. POSITION MANAGEMENT (Dynamic Exits)
        active_symbols = list(self.positions.keys())
        
        for symbol in active_symbols:
            pos = self.positions[symbol]
            market_data = prices.get(symbol)
            
            if not market_data:
                continue
                
            try:
                current_price = float(market_data["priceUsd"])
                pos["ticks_held"] += 1
                
                # Update history for indicator calculation
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.history_len)
                self.price_history[symbol].append(current_price)
                
                # EXIT LOGIC
                should_close = False
                reason_tag = ""
                
                # A. Hard Stop (Safety net, not trailing)
                entry_price = pos["entry_price"]
                pnl_pct = (current_price - entry_price) / entry_price
                
                if pnl_pct <= -self.stop_loss_pct:
                    should_close = True
                    reason_tag = "HARD_STOP"
                
                # B. Time Decay
                elif pos["ticks_held"] >= self.max_hold_ticks:
                    should_close = True
                    reason_tag = "TIMEOUT"
                    
                # C. Dynamic Signal Exit (RSI Reversion)
                # Addresses 'FIXED_TP' by using market structure exit
                else:
                    history_list = list(self.price_history[symbol])
                    current_rsi = self._calculate_rsi(history_list, self.rsi_period)
                    
                    if current_rsi > self.rsi_exit_level:
                        should_close = True
                        reason_tag = f"RSI_EXIT:{current_rsi:.0f}"
                
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
                price = float(data["priceUsd"])
                liquidity = float(data.get("liquidity", 0))
                
                # Liquidity Filter
                if liquidity < self.min_liquidity:
                    continue
                    
                # Update History
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.history_len)
                
                self.price_history[symbol].append(price)
                history_list = list(self.price_history[symbol])
                
                if len(history_list) < self.history_len:
                    continue
                    
                # 3. ANALYSIS
                # Trend Filter: Price > EMA (Uptrend)
                # We only buy dips in uptrends to avoid 'Catching Falling Knives' (Crash)
                ema_trend = self._calculate_ema(history_list, self.ema_trend_period)
                if ema_trend is None or price < ema_trend:
                    continue
                
                # Momentum Trigger: Fast RSI
                rsi = self._calculate_rsi(history_list, self.rsi_period)
                
                # Signal: Deep Oversold
                if rsi < self.rsi_buy_level:
                    candidates.append({
                        "symbol": symbol,
                        "price": price,
                        "rsi": rsi,
                        "trend_strength": (price / ema_trend)
                    })
                    
            except (ValueError, TypeError, KeyError):
                continue
                
        # 4. EXECUTION
        if candidates:
            # Sort by lowest RSI (Deepest value relative to recent action)
            best_opp = min(candidates, key=lambda x: x["rsi"])
            
            position_value = self.balance * self.trade_size_pct
            amount = position_value / best_opp["price"]
            
            self.positions[best_opp["symbol"]] = {
                "amount": amount,
                "entry_price": best_opp["price"],
                "ticks_held": 0
            }
            
            return {
                "side": "BUY",
                "symbol": best_opp["symbol"],
                "amount": amount,
                "reason": ["SNAP_BACK", f"RSI:{best_opp['rsi']:.1f}"]
            }
            
        return None