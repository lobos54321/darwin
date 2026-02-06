# Darwin SDK - User Strategy Template
# Agent: Degen_Ape_693
# Strategy: Evolutionary Momentum v3.0 (Adaptive Trend + Volatility Gating)
# Status: EVOLVED

import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized: Evo-Momentum v3.0")
        
        # --- Configuration (Genetics) ---
        self.window_size = 30           # Ticks for EMA/Vol calc
        self.ema_alpha = 0.15           # Smoothing factor for EMA
        self.vol_gate_min = 0.1         # Minimum volatility to enter (avoid chop)
        self.vol_gate_max = 5.0         # Max volatility to enter (avoid falling knives)
        self.trailing_stop_pct = 0.04   # 4% Trailing Stop
        self.take_profit_pct = 0.12     # 12% Take Profit
        self.cooldown_ticks = 10        # Ticks to wait after exit
        
        # --- State ---
        self.prices_history = {}        # {symbol: deque(maxlen=N)}
        self.ema_values = {}            # {symbol: float}
        self.positions = {}             # {symbol: {'entry': float, 'high': float, 'size': float}}
        self.cooldowns = {}             # {symbol: int}
        self.banned_tags = set()

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Hive Penalty: {penalize}")
            self.banned_tags.update(penalize)
            # Immediate liquidation of banned assets
            for tag in penalize:
                if tag in self.positions:
                    self.positions[tag]['force_exit'] = True

    def _update_indicators(self, symbol, price):
        """Update EMA and History"""
        if symbol not in self.prices_history:
            self.prices_history[symbol] = deque(maxlen=self.window_size)
            self.ema_values[symbol] = price
        
        self.prices_history[symbol].append(price)
        
        # Update EMA
        prev_ema = self.ema_values[symbol]
        self.ema_values[symbol] = (price * self.ema_alpha) + (prev_ema * (1 - self.ema_alpha))

    def _get_volatility(self, symbol):
        """Calculate StdDev of recent prices"""
        if len(self.prices_history.get(symbol, [])) < 5:
            return 0.0
        return statistics.stdev(self.prices_history[symbol])

    def on_price_update(self, prices: dict):
        """
        Main Execution Loop
        """
        actions = [] # List of orders to return
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # 0. Filter Banned Assets
            if symbol in self.banned_tags:
                if symbol in self.positions:
                    actions.append({"action": "SELL", "symbol": symbol, "reason": "BANNED"})
                    del self.positions[symbol]
                continue

            # 1. Update State
            self._update_indicators(symbol, current_price)
            
            # Decrease cooldown
            if self.cooldowns.get(symbol, 0) > 0:
                self.cooldowns[symbol] -= 1
                
            # 2. Manage Existing Positions (Risk Management)
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Update High Water Mark
                if current_price > pos['high']:
                    pos['high'] = current_price
                
                # Check Trailing Stop
                drawdown = (pos['high'] - current_price) / pos['high']
                # Check Hard Take Profit
                profit = (current_price - pos['entry']) / pos['entry']
                
                if drawdown >= self.trailing_stop_pct:
                    actions.append({"action": "SELL", "symbol": symbol, "reason": "TRAILING_STOP"})
                    self.cooldowns[symbol] = self.cooldown_ticks
                    del self.positions[symbol]
                    
                elif profit >= self.take_profit_pct:
                    actions.append({"action": "SELL", "symbol": symbol, "reason": "TAKE_PROFIT"})
                    self.cooldowns[symbol] = self.cooldown_ticks
                    del self.positions[symbol]
                    
                continue # Skip entry logic if we hold position

            # 3. Check New Entries (Strategy Logic)
            if self.cooldowns.get(symbol, 0) > 0:
                continue

            history = self.prices_history[symbol]
            if len(history) < self.window_size:
                continue

            ema = self.ema_values[symbol]
            vol = self._get_volatility(symbol)
            
            # Volatility Gating (Avoid flat markets and extreme chaos)
            vol_pct = (vol / current_price) * 100
            if not (self.vol_gate_min < vol_pct < self.vol_gate_max):
                continue

            # Trend Confirmation: Price > EMA AND Price is rising relative to 3 ticks ago
            momentum_lookback = 3
            if len(history) > momentum_lookback:
                past_price = history[-momentum_lookback]
                momentum = (current_price - past_price) / past_price
                
                # ENTRY CONDITION:
                # 1. Uptrend (Price > EMA)
                # 2. Strong Momentum (> 0.2%)
                # 3. No Bans
                if current_price > ema and momentum > 0.002:
                    # Calculate dynamic position size based on volatility (Kelly-lite)
                    # Lower size for higher volatility
                    risk_factor = 1.0 / (vol_pct + 0.1) 
                    size = min(risk_factor * 100, 1000) # Cap size
                    
                    self.positions[symbol] = {
                        'entry': current_price,
                        'high': current_price,
                        'size': size
                    }
                    actions.append({"action": "BUY", "symbol": symbol, "amount": size})

        return actions