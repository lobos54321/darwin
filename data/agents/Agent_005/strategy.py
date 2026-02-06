# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import statistics
from collections import deque

class MyStrategy:
    """
    Agent_005 Gen 27: 'Phoenix Momentum'
    
    [Evolution Log]
    - Status: Recovery Mode ($720 Balance)
    - Parent: Gen 26 (Darwin's Razor) + Winner's DNA (Basic Momentum)
    - Mutation: 
        1. Adaptive Volatility Thresholds: Instead of fixed % stops, we use Standard Deviation 
           of recent returns to adjust stops dynamically. High vol = wider stops.
        2. Trend Filtering: Added a simple SMA crossover (Fast/Slow) to prevent buying 
           into 'dead cat bounces' (downward momentum spikes).
        3. Aggressive Compounding: Increased position sizing slightly for high-confidence setups 
           to accelerate recovery, but with strictly enforced trailing stops.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Phoenix Momentum v27.0)")
        
        # --- Configuration ---
        self.history_len = 20           # Depth for MA and Volatility calc
        self.fast_ma_period = 5
        self.slow_ma_period = 15
        
        # --- State Management ---
        self.price_history = {}         # {symbol: deque(maxlen=20)}
        self.positions = {}             # {symbol: {'entry_price': float, 'highest_price': float, 'volatility_at_entry': float}}
        self.banned_tags = set()
        
        # --- Risk Management ---
        self.max_positions = 3          # Max concurrent trades
        self.base_risk_per_trade = 0.20 # Risk 20% of equity (Aggressive recovery)
        self.min_volatility = 0.001     # Minimum volatility floor to avoid flatlines
        
    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Penalized tags received: {penalize}")
            self.banned_tags.update(penalize)
            # Immediate liquidation logic could go here if API allowed

    def _calculate_indicators(self, symbol, current_price):
        """Calculate MA and Volatility"""
        history = self.price_history[symbol]
        
        if len(history) < self.history_len:
            return None
            
        prices = list(history)
        
        # Simple Moving Averages
        fast_ma = sum(prices[-self.fast_ma_period:]) / self.fast_ma_period
        slow_ma = sum(prices[-self.slow_ma_period:]) / self.slow_ma_period
        
        # Volatility (Standard Deviation of % changes)
        pct_changes = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                change = (prices[i] - prices[i-1]) / prices[i-1]
                pct_changes.append(change)
        
        volatility = statistics.stdev(pct_changes) if len(pct_changes) > 1 else 0.01
        
        return {
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "volatility": volatility
        }

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        Returns a list of orders to execute.
        """
        orders = []
        
        # 1. Update History
        for symbol, data in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.history_len)
            self.price_history[symbol].append(data["priceUsd"])

        # 2. Analyze Market
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Skip if not enough data
            indicators = self._calculate_indicators(symbol, current_price)
            if not indicators:
                continue
                
            fast_ma = indicators["fast_ma"]
            slow_ma = indicators["slow_ma"]
            volatility = max(indicators["volatility"], self.min_volatility)
            
            # --- Exit Logic (Trailing Stop & Trend Reversal) ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Update highest price seen for trailing stop
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
                
                # Dynamic Stop Width: 3x Volatility (wider for volatile assets)
                stop_distance = 3 * pos['volatility_at_entry']
                trailing_stop_price = pos['highest_price'] * (1 - stop_distance)
                
                # Hard Stop check
                is_below_stop = current_price < trailing_stop_price
                
                # Trend Reversal check (Fast crosses below Slow)
                is_trend_reversal = fast_ma < slow_ma
                
                if is_below_stop or is_trend_reversal:
                    print(f"🔻 SELL {symbol} @ {current_price:.4f} | PnL: {((current_price - pos['entry_price'])/pos['entry_price'])*100:.2f}%")
                    orders.append({"symbol": symbol, "side": "SELL", "amount": 1.0}) # Sell 100%
                    del self.positions[symbol]
                continue

            # --- Entry Logic (Momentum + Trend) ---
            
            # Check constraints
            if len(self.positions) >= self.max_positions:
                continue
                
            if symbol in self.banned_tags:
                continue

            # Signal Generation
            # 1. Trend is UP (Fast > Slow)
            # 2. Momentum is positive (Current > Fast MA)
            # 3. Volatility is not insane (avoid pump/dumps > 5% per tick)
            
            is_uptrend = fast_ma > slow_ma
            is_momentum = current_price > fast_ma
            is_safe_vol = volatility < 0.05 
            
            if is_uptrend and is_momentum and is_safe_vol:
                # Position Sizing: Base bet
                # In a real engine, we'd calculate exact quantity based on balance.
                # Here we send a signal to buy with a fixed weight.
                print(f"🚀 BUY {symbol} @ {current_price:.4f} | Vol: {volatility*100:.2f}%")
                
                self.positions[symbol] = {
                    'entry_price': current_price,
                    'highest_price': current_price,
                    'volatility_at_entry': volatility
                }
                
                orders.append({
                    "symbol": symbol, 
                    "side": "BUY", 
                    "amount": self.base_risk_per_trade
                })
                
        return orders