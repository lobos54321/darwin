# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import statistics
import math
from collections import deque, defaultdict

class MyStrategy:
    """
    Agent_005 Gen 33: 'Phoenix Reflex'
    
    [Evolution Log]
    - Status: Critical Recovery ($720 Balance)
    - Parent: Gen 32 (Lazarus Vector)
    - Source of Wisdom: Adopted Winner's immediate price-action focus (Momentum).
    - Mutation: 
        1. Volatility-Adjusted Momentum (VAM): Only trades when velocity exceeds local noise (Standard Deviation).
        2. 'Phoenix' Sizing: Dynamic position sizing based on account health. Drastically reduced risk while under $900.
        3. Time-Based Decay: If momentum doesn't yield profit within 5 ticks, exit immediately (Time Stop).
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Phoenix Reflex v33.0)")
        
        # --- Configuration ---
        self.volatility_window = 10
        self.momentum_window = 3
        self.max_positions = 4
        
        # --- State ---
        self.price_history = defaultdict(lambda: deque(maxlen=20))
        self.positions = {}  # {symbol: {'entry': float, 'ticks': int, 'highest': float}}
        self.cooldowns = defaultdict(int) # symbol -> ticks remaining
        self.banned_tags = set()
        
        # --- Risk Parameters ---
        # Recovery Mode: If balance < 1000, trade smaller.
        self.base_bet_size = 50.0 # USD
        self.hard_stop_loss = 0.03 # 3%
        self.take_profit = 0.08    # 8%
        self.trailing_trigger = 0.02 # Activate trailing after 2% gain

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)

    def get_volatility(self, symbol):
        """Calculate standard deviation of recent prices"""
        if len(self.price_history[symbol]) < self.volatility_window:
            return 0.0
        prices = list(self.price_history[symbol])[-self.volatility_window:]
        if len(prices) < 2: 
            return 0.0
        return statistics.stdev(prices)

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        Returns: ('buy', symbol, amount) or ('sell', symbol, 1.0) or None
        """
        decision = None
        
        # 1. Update Data & Cooldowns
        for symbol, data in prices.items():
            self.price_history[symbol].append(data["priceUsd"])
            if self.cooldowns[symbol] > 0:
                self.cooldowns[symbol] -= 1

        # 2. Manage Active Positions (Exits)
        # We iterate a copy of keys to allow modification of dict during iteration
        for symbol in list(self.positions.keys()):
            current_price = prices[symbol]["priceUsd"]
            pos_data = self.positions[symbol]
            entry_price = pos_data['entry']
            
            # Update highest price seen for trailing stop
            if current_price > pos_data['highest']:
                self.positions[symbol]['highest'] = current_price
            
            # Calculate PnL percentage
            pnl_pct = (current_price - entry_price) / entry_price
            
            # Increment time counter
            self.positions[symbol]['ticks'] += 1
            
            # A. Hard Stop Loss
            if pnl_pct <= -self.hard_stop_loss:
                print(f"🛑 SL Triggered: {symbol} @ {pnl_pct:.2%}")
                self.cooldowns[symbol] = 10 # Penalty cooldown
                del self.positions[symbol]
                return ("sell", symbol, 1.0) # Sell 100%
            
            # B. Trailing Stop Logic
            # If price rose X%, stop moves up. 
            # Simple implementation: If we drop Y% from highest, sell.
            drawdown_from_peak = (current_price - pos_data['highest']) / pos_data['highest']
            if pnl_pct > self.trailing_trigger and drawdown_from_peak < -0.015: # 1.5% drop from peak
                print(f"💰 Trailing TP: {symbol} (Peak: {pos_data['highest']})")
                del self.positions[symbol]
                return ("sell", symbol, 1.0)

            # C. Time Decay Stop (Stalemate Breaker)
            # If 8 ticks passed and we are barely profitable or negative, cut it.
            if self.positions[symbol]['ticks'] > 8 and pnl_pct < 0.005:
                print(f"⌛ Time Decay Exit: {symbol}")
                del self.positions[symbol]
                return ("sell", symbol, 1.0)

            # D. Hard Take Profit
            if pnl_pct >= self.take_profit:
                print(f"🚀 Hard TP: {symbol} @ {pnl_pct:.2%}")
                del self.positions[symbol]
                return ("sell", symbol, 1.0)

        # 3. Scan for New Entries (Only if slots available)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol, data in prices.items():
                # Skip if active, cooled down, or banned
                if symbol in self.positions or self.cooldowns[symbol] > 0 or symbol in self.banned_tags:
                    continue
                
                history = self.price_history[symbol]
                if len(history) < self.volatility_window:
                    continue
                
                current_price = data["priceUsd"]
                prev_price_short = history[-min(len(history), self.momentum_window)]
                
                # Logic: Momentum
                momentum_pct = (current_price - prev_price_short) / prev_price_short
                
                # Logic: Volatility Filter
                # We only want to trade if the move is "abnormal" (stronger than noise)
                vol = self.get_volatility(symbol)
                threshold = (vol / current_price) * 1.5 # 1.5 Sigma move
                
                # Avoid division by zero/low vol traps
                if threshold < 0.001: threshold = 0.001
                
                if momentum_pct > threshold:
                    # Score based on momentum strength vs volatility
                    score = momentum_pct / threshold
                    candidates.append((score, symbol, current_price))
            
            # Execute best candidate
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                best_score, best_symbol, best_price = candidates[0]
                
                # Sizing: Conservative fixed amount to rebuild confidence
                # If we are in deep drawdown, stick to base_bet_size
                trade_size = self.base_bet_size
                
                print(f"⚡ Entry: {best_symbol} (Score: {best_score:.2f})")
                
                self.positions[best_symbol] = {
                    'entry': best_price,
                    'highest': best_price,
                    'ticks': 0
                }
                return ("buy", best_symbol, trade_size)

        return decision