# Darwin SDK - User Strategy Template
# 🧬 AGENT: Bo_Bot | GEN: 76 | CODENAME: KINETIC_SCALPER_V1
# -----------------------------------------------------------------------------
# Evolution Log (Gen 76):
# 1. CRITICAL FIX: Removed lagging indicators (EMA). Switched to Tick-Velocity.
# 2. RISK PROTOCOL: Implemented strict "Time-Decay" stops. If a trade doesn't 
#    perform immediately, it is cut. No holding bags.
# 3. MUTATION: "Volatility Breakout". Buys only when price exceeds the 
#    upper bound of recent variance (Bollinger-style logic on micro-timeframes).
# -----------------------------------------------------------------------------

import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (Gen 76: Kinetic Scalper)")
        
        # --- Configuration ---
        self.MAX_HISTORY = 15           # Ticks to keep for volatility calc
        self.VOLATILITY_MULTIPLIER = 1.8 # StdDev multiplier for breakout
        self.MIN_MOMENTUM = 0.002       # Min 0.2% change to trigger buy
        self.TRAILING_STOP_PCT = 0.015  # 1.5% trailing stop
        self.HARD_STOP_PCT = 0.03       # 3% hard stop
        self.TIME_STOP_TICKS = 10       # Sell if stagnant for 10 ticks
        self.MAX_POSITIONS = 5          # Max active trades
        
        # --- State ---
        self.price_history = {}         # {symbol: deque([p1, p2...])}
        self.holdings = {}              # {symbol: {'entry': float, 'max': float, 'ticks': int}}
        self.banned_tags = set()
        self.cooldowns = {}             # {symbol: int_ticks}

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Penalty received: {penalize}")
            self.banned_tags.update(penalize)
            # Immediate liquidation of penalized assets
            for symbol in penalize:
                if symbol in self.holdings:
                    del self.holdings[symbol]

    def _calculate_volatility_stats(self, prices):
        if len(prices) < 5:
            return None, None
        
        mean_price = statistics.mean(prices)
        stdev = statistics.stdev(prices) if len(prices) > 1 else 0
        return mean_price, stdev

    def on_price_update(self, prices: dict):
        """
        High-frequency decision loop.
        Returns a list of orders: [{"symbol": str, "side": "BUY"|"SELL", "amount": float}]
        """
        orders = []
        
        # 1. Update Data & Cooldowns
        active_symbols = list(prices.keys())
        for symbol in list(self.cooldowns.keys()):
            self.cooldowns[symbol] -= 1
            if self.cooldowns[symbol] <= 0:
                del self.cooldowns[symbol]

        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Initialize history
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.MAX_HISTORY)
            self.price_history[symbol].append(current_price)

            # --- SELL LOGIC (Risk Management First) ---
            if symbol in self.holdings:
                position = self.holdings[symbol]
                position['ticks'] += 1
                
                # Update High-Water Mark
                if current_price > position['max']:
                    position['max'] = current_price
                
                # Logic A: Hard Stop Loss
                drawdown_entry = (current_price - position['entry']) / position['entry']
                
                # Logic B: Trailing Stop
                drawdown_peak = (current_price - position['max']) / position['max']
                
                # Logic C: Time Stop (Stagnation)
                is_stagnant = position['ticks'] > self.TIME_STOP_TICKS and drawdown_entry < 0.005
                
                should_sell = False
                reason = ""
                
                if drawdown_entry < -self.HARD_STOP_PCT:
                    should_sell = True
                    reason = "Hard Stop"
                elif drawdown_peak < -self.TRAILING_STOP_PCT:
                    should_sell = True
                    reason = "Trailing Stop"
                elif is_stagnant:
                    should_sell = True
                    reason = "Time Decay"
                
                if should_sell:
                    print(f"🔻 SELL {symbol} | Reason: {reason} | PnL: {drawdown_entry*100:.2f}%")
                    orders.append({"symbol": symbol, "side": "SELL", "amount": 1.0}) # Sell 100%
                    del self.holdings[symbol]
                    self.cooldowns[symbol] = 5 # Short cooldown after loss
                    continue # Skip buy logic for this symbol

            # --- BUY LOGIC (Opportunity Scanning) ---
            # Criteria: Not held, not banned, not cooling down, slots available
            if (symbol not in self.holdings and 
                symbol not in self.banned_tags and 
                symbol not in self.cooldowns and 
                len(self.holdings) < self.MAX_POSITIONS):
                
                history = self.price_history[symbol]
                mean, stdev = self._calculate_volatility_stats(history)
                
                if mean and stdev > 0:
                    # Bollinger Upper Band
                    upper_band = mean + (stdev * self.VOLATILITY_MULTIPLIER)
                    
                    # Momentum Calculation (ROC)
                    pct_change = (current_price - history[0]) / history[0]
                    
                    # Buy Trigger: Price breaks upper band AND has positive momentum
                    if current_price > upper_band and pct_change > self.MIN_MOMENTUM:
                        print(f"🚀 BUY {symbol} | Price: {current_price} | Breakout: {pct_change*100:.2f}%")
                        # Position Sizing: Equal weight based on max slots
                        amount = 1.0 / self.MAX_POSITIONS 
                        orders.append({"symbol": symbol, "side": "BUY", "amount": amount})
                        
                        self.holdings[symbol] = {
                            'entry': current_price,
                            'max': current_price,
                            'ticks': 0
                        }

        return orders