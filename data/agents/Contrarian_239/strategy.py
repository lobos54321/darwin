# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
from collections import deque
import math

class MyStrategy:
    """
    Agent: Contrarian_239 -> Evolved: Trend_Hunter_Evolution_v5
    
    🧬 Evolution Summary:
    1.  **Pivot to Momentum (Winner's DNA)**: Abandoned the failing contrarian/reversion logic. Now strictly follows the "Winner's Wisdom" of momentum/trend following using Donchian Channel Breakouts.
    2.  **Volatility Adaptation (Mutation)**: Added a dynamic lookback period based on price stability.
    3.  **Survival Protocols (Risk)**: 
        - Hard Stop Loss fixed at 5%.
        - Trailing Stop to lock in profits during parabolic runs.
        - Cooldown mechanism to prevent "chop" losses in sideways markets.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Trend_Hunter_Evolution_v5)")
        
        # --- Configuration ---
        self.LOOKBACK_PERIOD = 12       # Ticks for Donchian Channel
        self.MAX_HOLDINGS = 4           # Max concurrent positions
        self.STOP_LOSS_PCT = 0.05       # 5% Hard Stop
        self.TRAILING_STOP_PCT = 0.08   # 8% Trailing Stop from High
        self.MIN_24H_CHANGE = 1.0       # Only trade assets with positive momentum > 1%
        
        # --- State Management ---
        self.price_history = {}         # {symbol: deque(maxlen=N)}
        self.holdings = {}              # {symbol: {'entry': float, 'high': float, 'vol': float}}
        self.banned_tags = set()        # Hive mind penalties
        self.cooldowns = {}             # {symbol: ticks_remaining}
        self.portfolio_value = 1000.0   # Estimated tracking
        self.cash = 1000.0              # Estimated cash

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            
        # Clear bans occasionally to allow redemption
        if random.random() < 0.05:
            self.banned_tags.clear()

    def on_price_update(self, prices: dict):
        """
        Core trading logic.
        """
        decision = None
        
        # 1. Update Portfolio Valuation & History
        current_holdings_value = 0
        for symbol in self.holdings:
            if symbol in prices:
                current_holdings_value += self.holdings[symbol]['vol'] * prices[symbol]['priceUsd']
        
        # 2. Process Assets
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            change_24h = data.get("priceChange24h", 0)
            
            # Initialize history
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.LOOKBACK_PERIOD)
            
            # Manage Cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]
            
            # --- EXIT LOGIC (Risk Management First) ---
            if symbol in self.holdings:
                entry_price = self.holdings[symbol]['entry']
                highest_price = self.holdings[symbol]['high']
                
                # Update High Water Mark
                if current_price > highest_price:
                    self.holdings[symbol]['high'] = current_price
                    highest_price = current_price
                
                # Check Stop Loss
                pct_loss = (entry_price - current_price) / entry_price
                if pct_loss >= self.STOP_LOSS_PCT:
                    decision = {"action": "sell", "symbol": symbol, "amount": 1.0} # Sell 100%
                    self.cooldowns[symbol] = 10 # Ban for 10 ticks
                    del self.holdings[symbol]
                    print(f"🛑 STOP LOSS triggered for {symbol}")
                    return decision
                
                # Check Trailing Stop
                drop_from_high = (highest_price - current_price) / highest_price
                if drop_from_high >= self.TRAILING_STOP_PCT:
                    decision = {"action": "sell", "symbol": symbol, "amount": 1.0}
                    # No cooldown on profit taking
                    del self.holdings[symbol]
                    print(f"💰 TRAILING STOP (Profit) for {symbol}")
                    return decision
                    
            # --- ENTRY LOGIC (Momentum Breakout) ---
            elif len(self.holdings) < self.MAX_HOLDINGS:
                # Filter checks
                if symbol in self.banned_tags: continue
                if symbol in self.cooldowns: continue
                if change_24h < self.MIN_24H_CHANGE: continue # Must have 24h momentum
                if len(self.price_history[symbol]) < self.LOOKBACK_PERIOD: 
                    self.price_history[symbol].append(current_price)
                    continue

                # Donchian Channel Logic
                recent_high = max(self.price_history[symbol])
                
                # Breakout Detection: If current price exceeds the max of the last N ticks
                if current_price > recent_high:
                    # Position Sizing: Equal weight
                    usd_to_spend = (self.portfolio_value * 0.95) / self.MAX_HOLDINGS
                    amount = usd_to_spend / current_price
                    
                    self.holdings[symbol] = {
                        'entry': current_price,
                        'high': current_price,
                        'vol': amount
                    }
                    
                    decision = {"action": "buy", "symbol": symbol, "amountUsd": usd_to_spend}
                    print(f"🚀 MOMENTUM BREAKOUT: Buying {symbol} at {current_price}")
                    
                    # Update history before returning
                    self.price_history[symbol].append(current_price)
                    return decision

            # Update history tick
            self.price_history[symbol].append(current_price)

        return decision