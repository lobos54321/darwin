# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import math
import statistics
from collections import deque

class MyStrategy:
    """
    Agent: Technical_Analyst_465 (v4.0 - Velocity Scalper)
    
    Evolution Log:
    1. [Simplification] Removed complex Bollinger Bands in favor of raw Velocity/Momentum.
    2. [Mutation] Added 'Global Sentiment Filter': Only buy when the broader market is trending up.
    3. [Risk] Tighter Trailing Stop (Dynamic) based on recent volatility.
    4. [Discipline] 'Penalty Box': Exponential backoff for assets that hit stop loss.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Velocity Scalper v4.0)")
        
        # === Configuration ===
        self.history_len = 10           # Keep last 10 ticks for volatility calc
        self.momentum_window = 3        # Check trend over last 3 ticks
        self.buy_threshold_pct = 0.5    # Price must jump 0.5% relative to average to buy
        
        # Risk Management
        self.hard_stop_loss = 0.03      # 3% Max loss per trade
        self.base_trailing_stop = 0.015 # 1.5% Trailing stop
        self.profit_target_tier1 = 0.05 # At 5% profit, tighten stop
        self.max_stagnation_ticks = 8   # Sell if price doesn't move for 8 ticks
        
        # === State ===
        # {symbol: deque([p1, p2...], maxlen=N)}
        self.price_history = {}
        
        # {symbol: {"entry_price": float, "highest_price": float, "entry_tick": int}}
        self.positions = {}
        
        # {symbol: tick_count_until_unban}
        self.penalty_box = {}
        
        self.banned_tags = set()
        self.tick_counter = 0

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🧠 Strategy received penalty for: {penalize}")
            self.banned_tags.update(penalize)

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        Returns a dictionary of actions: {"SYMBOL": "BUY" | "SELL"}
        """
        self.tick_counter += 1
        decisions = {}
        
        # 1. Update History & Calculate Global Sentiment
        market_moves = []
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.history_len)
            self.price_history[symbol].append(current_price)
            
            # Track instant change for sentiment
            if len(self.price_history[symbol]) >= 2:
                prev_price = self.price_history[symbol][-2]
                pct_change = (current_price - prev_price) / prev_price
                market_moves.append(pct_change)
        
        # Global Sentiment Check (Simple Majority)
        bullish_market = False
        if market_moves:
            avg_market_move = sum(market_moves) / len(market_moves)
            bullish_market = avg_market_move > 0
            
        # 2. Process Decrementing Penalties
        symbols_to_free = []
        for sym, ticks_left in self.penalty_box.items():
            if ticks_left <= 0:
                symbols_to_free.append(sym)
            else:
                self.penalty_box[sym] -= 1
        for sym in symbols_to_free:
            del self.penalty_box[sym]

        # 3. Strategy Logic per Symbol
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            history = self.price_history[symbol]
            
            # --- MANAGE EXISTING POSITIONS ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Update Highest Price (High Water Mark)
                if current_price > pos["highest_price"]:
                    pos["highest_price"] = current_price
                
                # Calculate metrics
                roi = (current_price - pos["entry_price"]) / pos["entry_price"]
                drawdown_from_peak = (pos["highest_price"] - current_price) / pos["highest_price"]
                ticks_held = self.tick_counter - pos["entry_tick"]
                
                # Dynamic Trailing Stop
                current_trailing_stop = self.base_trailing_stop
                if roi > self.profit_target_tier1:
                    # Tighten stop if we are in deep profit to lock gains
                    current_trailing_stop = 0.005 # 0.5% tight stop
                
                should_sell = False
                reason = ""
                
                # A. Hard Stop Loss
                if roi < -self.hard_stop_loss:
                    should_sell = True
                    reason = "Stop Loss"
                    # Penalty: Ban for 20 ticks if stopped out
                    self.penalty_box[symbol] = 20
                
                # B. Trailing Stop
                elif drawdown_from_peak > current_trailing_stop:
                    should_sell = True
                    reason = "Trailing Stop"
                
                # C. Stagnation Exit (Time Decay)
                elif ticks_held > self.max_stagnation_ticks and roi < 0.005:
                    should_sell = True
                    reason = "Stagnation"
                    
                if should_sell:
                    print(f"📉 SELLING {symbol} ({reason}) ROI: {roi*100:.2f}%")
                    decisions[symbol] = "SELL"
                    del self.positions[symbol]
                    
            # --- FIND NEW ENTRIES ---
            else:
                # Filter 1: Global Market Condition
                if not bullish_market:
                    continue
                    
                # Filter 2: Penalties & History
                if symbol in self.penalty_box or symbol in self.banned_tags:
                    continue
                if len(history) < self.momentum_window + 1:
                    continue
                
                # Logic: Velocity Breakout
                # Check if price is strictly increasing over the momentum window
                is_trending_up = True
                for i in range(1, self.momentum_window + 1):
                    if history[-i] <= history[-(i+1)]:
                        is_trending_up = False
                        break
                
                # Check volatility expansion (Current move > Average recent moves)
                recent_volatility = statistics.stdev(list(history)) if len(history) > 2 else 0
                avg_price = sum(history) / len(history)
                
                # Relative breakout strength
                if avg_price > 0:
                    deviation_pct = (current_price - avg_price) / avg_price * 100
                else:
                    deviation_pct = 0
                
                # Entry Signal
                if is_trending_up and deviation_pct > self.buy_threshold_pct:
                    print(f"🚀 BUYING {symbol} (Trend + Breakout {deviation_pct:.2f}%)")
                    decisions[symbol] = "BUY"
                    self.positions[symbol] = {
                        "entry_price": current_price,
                        "highest_price": current_price,
                        "entry_tick": self.tick_counter
                    }

        return decisions