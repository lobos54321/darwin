# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import math
from collections import deque
from typing import Dict, List, Optional, Tuple

class MyStrategy:
    """
    Agent: Value_Investor_113 (Gen 4: Adaptive Trend-Flow)
    
    Evolution Changelog:
    1.  Simplified Core: Abandoned complex micro-structure analysis for robust EMA Trend Following.
    2.  Volatility Scaling: Position sizing is now inversely proportional to asset volatility.
    3.  Trailing Survival: Implemented a dynamic trailing stop that tightens as profits grow.
    4.  Anti-Fragility: Added cooldown periods to prevent "revenge trading" after a loss.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Gen 4: Adaptive Trend-Flow)")
        
        # === Configuration ===
        self.fast_window = 5
        self.slow_window = 20
        self.max_history = 30
        
        # Risk Management
        self.base_risk_per_trade = 0.15  # 15% of capital per trade
        self.hard_stop_loss = 0.07       # 7% hard stop
        self.trailing_trigger = 0.05     # Activate trailing after 5% gain
        self.cooldown_ticks = 10         # Wait 10 ticks after selling before re-entry
        
        # === State ===
        self.history: Dict[str, deque] = {}
        self.positions: Dict[str, dict] = {} # {symbol: {'entry': float, 'high': float, 'amount': float}}
        self.cooldowns: Dict[str, int] = {}
        self.banned_tags = set()
        
        # Mock Balance (In a real scenario, this would be fetched from the engine)
        self.balance = 536.69 

    def on_hive_signal(self, signal: dict):
        """Handle Hive Mind signals for immediate risk mitigation."""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            # Logic to force close positions on penalized tags would happen in the next update loop

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        if not prices: return 0.0
        k = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price * k) + (ema * (1 - k))
        return ema

    def _get_volatility(self, prices: List[float]) -> float:
        if len(prices) < 2: return 0.0
        changes = [abs(prices[i] - prices[i-1])/prices[i-1] for i in range(1, len(prices))]
        return sum(changes) / len(changes)

    def on_price_update(self, prices: dict) -> Optional[Tuple[str, str, float]]:
        """
        Main decision loop.
        Returns: (action, symbol, amount) or None
        action: "buy" | "sell"
        """
        
        # 1. Update Data & Manage Cooldowns
        active_symbols = list(prices.keys())
        random.shuffle(active_symbols) # Shuffle to avoid bias in processing order
        
        decision = None
        
        for symbol in active_symbols:
            current_price = prices[symbol]["priceUsd"]
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.max_history)
            self.history[symbol].append(current_price)
            
            # Manage Cooldown
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]
                continue # Skip trading this symbol if in cooldown

            # === Check Existing Positions (Exit Logic) ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos['entry']
                amount = pos['amount']
                
                # Update High Watermark
                if current_price > pos['high']:
                    pos['high'] = current_price
                
                # Calculate PnL
                pnl_pct = (current_price - entry_price) / entry_price
                drawdown_from_high = (pos['high'] - current_price) / pos['high']
                
                # 1. Hive Ban Exit
                if symbol in self.banned_tags:
                    print(f"🚫 Selling {symbol}: Banned by Hive")
                    del self.positions[symbol]
                    self.balance += current_price * amount
                    return ("sell", symbol, amount)

                # 2. Hard Stop Loss
                if pnl_pct < -self.hard_stop_loss:
                    print(f"🛑 Stop Loss {symbol}: {pnl_pct*100:.2f}%")
                    del self.positions[symbol]
                    self.cooldowns[symbol] = self.cooldown_ticks # Penalty cooldown
                    self.balance += current_price * amount
                    return ("sell", symbol, amount)
                
                # 3. Trailing Stop Profit
                # If we are up significantly, tighten the stop
                dynamic_trail = 0.03 if pnl_pct > 0.10 else 0.05
                if pnl_pct > self.trailing_trigger and drawdown_from_high > dynamic_trail:
                    print(f"💰 Take Profit (Trailing) {symbol}: {pnl_pct*100:.2f}%")
                    del self.positions[symbol]
                    self.balance += current_price * amount
                    return ("sell", symbol, amount)
                    
                continue # Holding position

            # === Check New Entries (Entry Logic) ===
            # Only buy if we have slots and not banned
            if len(self.positions) < 4 and symbol not in self.banned_tags:
                history = list(self.history[symbol])
                if len(history) < self.slow_window:
                    continue
                
                ema_fast = self._calculate_ema(history[-self.fast_window:], self.fast_window)
                ema_slow = self._calculate_ema(history[-self.slow_window:], self.slow_window)
                volatility = self._get_volatility(history[-10:])
                
                # Trend Condition: Fast > Slow (Uptrend)
                # Momentum Condition: Price currently above Fast EMA
                # Volatility Safety: Don't buy if volatility is insane (>5% per tick avg)
                if ema_fast > ema_slow and current_price > ema_fast and volatility < 0.05:
                    
                    # Entry Signal Detected
                    
                    # Position Sizing based on Volatility (Kelly Criterion simplified)
                    # Lower vol = larger size, Higher vol = smaller size
                    risk_factor = max(0.01, volatility * 10)
                    bet_size_usd = self.balance * (self.base_risk_per_trade / (1 + risk_factor))
                    
                    # Cap bet size
                    bet_size_usd = min(bet_size_usd, self.balance * 0.25)
                    
                    if bet_size_usd > 10.0: # Minimum trade size
                        amount_to_buy = bet_size_usd / current_price
                        self.positions[symbol] = {
                            'entry': current_price,
                            'high': current_price,
                            'amount': amount_to_buy
                        }
                        self.balance -= bet_size_usd
                        print(f"🚀 Buying {symbol} at ${current_price:.4f} (Vol: {volatility:.4f})")
                        return ("buy", symbol, amount_to_buy)

        return None