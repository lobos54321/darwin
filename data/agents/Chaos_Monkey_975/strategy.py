# Darwin SDK - User Strategy Template
# 🧬 AGENT: Chaos_Monkey_975 (Evolution Gen 4: Adaptive Reversion)
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import math
import statistics
import random
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (Gen 4: Adaptive Reversion - Recovery Mode)")
        
        # --- 核心参数 (Evolution: Balanced Risk/Reward) ---
        self.window_size = 20           # Bollinger Band window
        self.std_dev_mult = 2.0         # Bollinger Band width
        self.rsi_period = 14            # Momentum check
        
        # --- 风控参数 (Risk Management) ---
        self.max_drawdown_per_trade = 0.04  # 4% Hard Stop Loss (Widened to prevent whipsaw)
        self.take_profit_pct = 0.08         # 8% Target Profit
        self.max_position_size = 0.20       # Max 20% of capital per trade (Aggressive recovery)
        self.cooldown_ticks = 10            # Wait periods after selling before rebuying
        
        # --- 状态管理 ---
        self.history = defaultdict(lambda: deque(maxlen=30)) # Price history
        self.positions = {}             # {symbol: {"entry": float, "size": float, "highest": float}}
        self.cooldowns = {}             # {symbol: int} - Remaining ticks to wait
        self.banned_tags = set()
        
        # Capital Tracking (Simulated for sizing)
        self.estimated_balance = 536.69 

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Penalty received for: {penalize}")
            self.banned_tags.update(penalize)
            # Immediate forced liquidation logic would happen in main loop via decision

    def _calculate_indicators(self, symbol):
        """Calculate Bollinger Bands and simple Momentum"""
        prices = list(self.history[symbol])
        if len(prices) < self.window_size:
            return None
        
        # Use recent window
        window = prices[-self.window_size:]
        sma = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0
        
        upper_band = sma + (stdev * self.std_dev_mult)
        lower_band = sma - (stdev * self.std_dev_mult)
        
        return {
            "sma": sma,
            "upper": upper_band,
            "lower": lower_band,
            "volatility": stdev / sma if sma > 0 else 0
        }

    def on_price_update(self, prices: dict):
        """
        Main trading logic loop.
        Returns: ("buy", symbol, amount) or ("sell", symbol, amount) or None
        """
        decision = None
        best_opportunity = None
        max_score = -float('inf')

        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # 1. Update History
            self.history[symbol].append(current_price)
            
            # 2. Handle Cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]
                continue

            # 3. Check Existing Positions (Risk Management)
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos["entry"]
                pos["highest"] = max(pos["highest"], current_price)
                
                # PnL Calculation
                pnl_pct = (current_price - entry_price) / entry_price
                drawdown_from_peak = (pos["highest"] - current_price) / pos["highest"]
                
                # SELL CONDITIONS:
                # A. Hard Stop Loss
                if pnl_pct < -self.max_drawdown_per_trade:
                    decision = ("sell", symbol, 1.0) # Sell 100%
                    self.cooldowns[symbol] = self.cooldown_ticks * 2 # Long cooldown on loss
                    print(f"🛡️ Stop Loss triggered for {symbol} at {pnl_pct:.2%}")
                    
                # B. Take Profit (Dynamic Trailing)
                elif pnl_pct > self.take_profit_pct and drawdown_from_peak > 0.02:
                    decision = ("sell", symbol, 1.0)
                    self.cooldowns[symbol] = self.cooldown_ticks
                    print(f"💰 Take Profit (Trailing) for {symbol} at {pnl_pct:.2%}")
                
                # C. Banned Tag Emergency Exit
                elif any(tag in self.banned_tags for tag in data.get("tags", [])):
                    decision = ("sell", symbol, 1.0)
                
                if decision:
                    del self.positions[symbol]
                    return decision # Execute one action per tick
                
                continue # Skip buying if we hold

            # 4. Look for Entry Opportunities (Mean Reversion)
            if symbol in self.banned_tags:
                continue

            indicators = self._calculate_indicators(symbol)
            if not indicators:
                continue
                
            # STRATEGY: Buy the dip in an uptrend (or extreme oversold)
            # Condition: Price touched Lower Band AND Volatility is healthy
            if current_price <= indicators["lower"]:
                # Scoring: Prefer higher volatility assets for recovery, but not insane
                score = indicators["volatility"] 
                
                # Filter: Don't catch falling knives blindly - verify price is not crashing too hard
                # (Simple check: Price > 0.95 * last_price to ensure it's not a flash crash)
                if len(self.history[symbol]) >= 2:
                    prev_price = self.history[symbol][-2]
                    if current_price < prev_price * 0.90:
                        score -= 10 # Avoid crash
                
                if score > max_score:
                    max_score = score
                    # Calculate position size based on balance
                    usd_amount = self.estimated_balance * self.max_position_size
                    best_opportunity = ("buy", symbol, usd_amount)

        # Execute best buy if no sells happened
        if best_opportunity:
            symbol = best_opportunity[1]
            price = prices[symbol]["priceUsd"]
            self.positions[symbol] = {
                "entry": price, 
                "size": best_opportunity[2], 
                "highest": price
            }
            return best_opportunity

        return None