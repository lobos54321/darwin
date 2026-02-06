# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import math
import statistics
from collections import deque

class MyStrategy:
    """
    Agent_005 Gen 29: 'Adaptive Resonance Survival'
    
    [Evolution Log]
    - Status: Emergency Protocol Activated ($720 Balance)
    - Parent: Gen 28 (Quantum Velocity)
    - Adaptation:
        1. Survival Mode: Position sizing reduced to fixed low-risk chunks to prevent ruin.
        2. Trend Confirmation: Replaced pure velocity with EMA Crossover (7/25) to filter noise.
        3. Volatility Gating: Only enters when volatility expands (breakout) but RSI is not overbought.
        4. Trailing Profit Lock: Aggressive trailing stop kicks in immediately after 1.5% profit.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Adaptive Resonance v29.0)")
        
        # --- Configuration ---
        self.ema_short_period = 7
        self.ema_long_period = 25
        self.rsi_period = 14
        self.history_len = 30
        
        # --- Risk Management ---
        self.max_positions = 5
        self.trade_size_usd = 60.0      # Reduced size to preserve capital (~8% of $720)
        self.stop_loss_pct = 0.03       # Tight 3% Hard Stop
        self.take_profit_pct = 0.12     # 12% Target
        self.trailing_trigger = 0.015   # Activate trail after 1.5% gain
        self.trailing_gap = 0.01        # Trail distance
        
        # --- State Tracking ---
        self.prices_history = {}        # {symbol: deque}
        self.positions = {}             # {symbol: {'entry': float, 'high': float, 'amount': float}}
        self.banned_tags = set()
        self.cooldowns = {}             # {symbol: ticks_remaining}

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)

    def _calculate_ema(self, prices, period):
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = prices[0] # Start with SMA logic or first price for simplicity in short windows
        # Calculate simple average for first chunk if needed, but iterative is faster for streams
        # Here we just iterate the slice provided
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_rsi(self, prices, period):
        if len(prices) < period + 1:
            return 50 # Neutral
        
        gains = []
        losses = []
        
        for i in range(1, period + 1):
            change = prices[-i] - prices[-(i+1)]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
                
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
            
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        """
        Main strategy loop.
        Returns a list of orders: [("BUY", "SYM", amt), ("SELL", "SYM", amt)]
        """
        orders = []
        
        # 1. Update History & Cooldowns
        active_symbols = set(prices.keys())
        
        for symbol, data in prices.items():
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.history_len)
            self.prices_history[symbol].append(data["priceUsd"])
            
            # Decrement cooldown
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # 2. Manage Existing Positions (Exit Logic)
        # Iterate over a copy of keys to allow deletion
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            current_price = prices[symbol]["priceUsd"]
            pos = self.positions[symbol]
            entry_price = pos['entry']
            
            # Update High Watermark
            if current_price > pos['high']:
                pos['high'] = current_price
            
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown_from_high = (pos['high'] - current_price) / pos['high']
            
            should_sell = False
            reason = ""
            
            # A. Hard Stop Loss
            if pnl_pct < -self.stop_loss_pct:
                should_sell = True
                reason = "STOP_LOSS"
                self.cooldowns[symbol] = 10 # Penalty box for losers
                
            # B. Take Profit
            elif pnl_pct > self.take_profit_pct:
                should_sell = True
                reason = "TAKE_PROFIT"
                
            # C. Trailing Stop
            elif pnl_pct > self.trailing_trigger and drawdown_from_high > self.trailing_gap:
                should_sell = True
                reason = "TRAILING_STOP"
            
            if should_sell:
                print(f"🔻 SELL {symbol} | PnL: {pnl_pct*100:.2f}% | Reason: {reason}")
                orders.append(("SELL", symbol, pos['amount']))
                del self.positions[symbol]

        # 3. Scan for New Entries (Entry Logic)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol, data in prices.items():
                # Filter: Active positions, Cooldowns, Banned Tags
                if symbol in self.positions or symbol in self.cooldowns:
                    continue
                
                # Check Tags (if available in data, otherwise skip tag check)
                tags = data.get("tags", [])
                if any(t in self.banned_tags for t in tags):
                    continue
                    
                history = list(self.prices_history[symbol])
                if len(history) < self.ema_long_period:
                    continue
                
                current_price = data["priceUsd"]
                
                # --- Indicators ---
                ema_short = self._calculate_ema(history, self.ema_short_period)
                ema_long = self._calculate_ema(history, self.ema_long_period)
                rsi = self._calculate_rsi(history, self.rsi_period)
                
                if ema_short is None or ema_long is None:
                    continue
                
                # --- Logic: Trend Following + Momentum Confirmation ---
                # 1. Golden Cross (Short EMA > Long EMA)
                trend_bullish = ema_short > ema_long
                
                # 2. RSI not overbought (Avoid buying the top)
                rsi_safe = 40 < rsi < 70
                
                # 3. Volume/Liquidity Check (Pseudo: Price > 0 and recent movement exists)
                # Calculating volatility (std dev of last 10 prices)
                recent_prices = history[-10:]
                if len(recent_prices) > 2:
                    volatility = statistics.stdev(recent_prices)
                    avg_p = statistics.mean(recent_prices)
                    rel_vol = volatility / avg_p if avg_p > 0 else 0
                else:
                    rel_vol = 0
                
                # Avoid dead coins (volatility too low)
                volatility_ok = rel_vol > 0.002 

                if trend_bullish and rsi_safe and volatility_ok:
                    # Score candidates by trend strength
                    score = (ema_short - ema_long) / ema_long
                    candidates.append((score, symbol, current_price))
            
            # Sort by strongest trend signal
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            # Execute Buys
            slots_available = self.max_positions - len(self.positions)
            for _, symbol, price in candidates[:slots_available]:
                print(f"🚀 BUY {symbol} | Price: {price} | Trend Score: {_:.4f}")
                self.positions[symbol] = {
                    'entry': price,
                    'high': price,
                    'amount': self.trade_size_usd
                }
                orders.append(("BUY", symbol, self.trade_size_usd))

        return orders