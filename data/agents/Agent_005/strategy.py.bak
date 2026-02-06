# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import statistics
from collections import deque

class MyStrategy:
    """
    Agent_005 Gen 30: 'Phoenix Reflex'
    
    [Evolution Log]
    - Status: Recovery Mode ($720 Balance)
    - Parent: Gen 29 (Adaptive Resonance)
    - Mutation Source: Analyzed Winner's tick-sensitivity.
    - Major Changes:
        1. Abandoned lagging indicators (EMA/RSI) for raw Price Action (Tick Velocity).
        2. Implemented 'Micro-Scalping': Enter on 3-tick alignment, exit on first momentum loss.
        3. Dynamic Risk: Position size scales with account balance (Kelly criterion lite).
        4. Time Decay: Force exit if trade stagnates for > 10 updates (don't tie up capital).
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Phoenix Reflex v30.0)")
        
        # --- Configuration ---
        self.tick_window = 5            # Look at last 5 price updates
        self.min_velocity = 0.002       # 0.2% move required to interest us
        self.max_volatility = 0.05      # Avoid if moves > 5% instantly (pump trap)
        
        # --- Risk Management (Recovery) ---
        self.max_concurrent_trades = 3
        self.base_risk_per_trade = 0.05 # Risk 5% of equity per trade
        self.hard_stop_loss = 0.025     # 2.5% Hard Stop
        self.profit_trail_start = 0.01  # Start trailing after 1% gain
        
        # --- State ---
        self.price_history = {}         # {symbol: deque([p1, p2, ...], maxlen=5)}
        self.positions = {}             # {symbol: {'entry': float, 'highest': float, 'age': int}}
        self.banned_tags = set()
        self.balance = 720.0            # Sync with actual balance

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            # Immediate liquidation of banned assets
            for tag in penalize:
                if tag in self.positions:
                    del self.positions[tag] # Simulating force close

    def _calculate_momentum(self, prices):
        """Calculate linear regression slope of last N prices for pure direction"""
        if len(prices) < 3:
            return 0
        y = list(prices)
        x = range(len(y))
        # Simple slope calculation
        x_bar = statistics.mean(x)
        y_bar = statistics.mean(y)
        numerator = sum((xi - x_bar) * (yi - y_bar) for xi, yi in zip(x, y))
        denominator = sum((xi - x_bar) ** 2 for xi in x)
        return numerator / denominator if denominator != 0 else 0

    def on_price_update(self, prices: dict):
        """
        High-frequency decision loop.
        """
        orders = []
        
        # 1. Update State & Prune History
        active_symbols = set(prices.keys())
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Init history
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.tick_window)
            self.price_history[symbol].append(current_price)

            # --- Manage Existing Positions ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos['age'] += 1
                entry_price = pos['entry']
                
                # Update highest price seen for trailing stop
                if current_price > pos['highest']:
                    pos['highest'] = current_price
                
                # PnL Calculation
                pnl_pct = (current_price - entry_price) / entry_price
                drawdown_from_peak = (pos['highest'] - current_price) / pos['highest']
                
                sell_signal = False
                reason = ""

                # A. Hard Stop Loss
                if pnl_pct < -self.hard_stop_loss:
                    sell_signal = True
                    reason = "Stop Loss"
                
                # B. Trailing Profit Take
                elif pnl_pct > self.profit_trail_start and drawdown_from_peak > 0.005:
                    sell_signal = True
                    reason = "Trailing Take Profit"
                
                # C. Time Decay (Stagnation Kill)
                elif pos['age'] > 10 and pnl_pct < 0.005:
                    sell_signal = True
                    reason = "Stagnation"

                if sell_signal:
                    orders.append({
                        "symbol": symbol,
                        "action": "SELL",
                        "amount": "ALL",
                        "reason": reason
                    })
                    del self.positions[symbol]
                    continue # Skip to next symbol

            # --- Entry Logic (Only if we have slots) ---
            if symbol not in self.positions and len(self.positions) < self.max_concurrent_trades:
                
                # Filter 1: Banned Tags
                if symbol in self.banned_tags:
                    continue

                # Filter 2: Data Sufficiency
                history = self.price_history[symbol]
                if len(history) < self.tick_window:
                    continue

                # Filter 3: Momentum Calculation
                slope = self._calculate_momentum(history)
                pct_change_window = (history[-1] - history[0]) / history[0]
                
                # Logic: Positive Slope + Significant Move + Not Hyper-Volatile
                is_uptrend = slope > 0
                is_significant = pct_change_window > self.min_velocity
                is_safe = pct_change_window < self.max_volatility
                
                # Check for "Tick Alignment" (Last 2 ticks green)
                tick_alignment = history[-1] > history[-2] and history[-2] > history[-3]

                if is_uptrend and is_significant and is_safe and tick_alignment:
                    # Dynamic Position Sizing
                    trade_amt = self.balance * self.base_risk_per_trade
                    
                    self.positions[symbol] = {
                        'entry': current_price,
                        'highest': current_price,
                        'age': 0
                    }
                    orders.append({
                        "symbol": symbol,
                        "action": "BUY",
                        "amount": trade_amt
                    })

        return orders