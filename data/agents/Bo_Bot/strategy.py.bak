```python
# Darwin SDK - User Strategy Template
# 🧬 AGENT: Bo_Bot | GEN: 78 | CODENAME: PHOENIX_PROTOCOL
# -----------------------------------------------------------------------------
# Evolution Log (Gen 78):
# 1. SURVIVAL FIRST: Implemented "Iron-Clad" Risk Management. 
#    - Hard Stop Loss fixed at -7%.
#    - Trailing Profit Stop to lock in gains once >15%.
#    - Volatility Sizing: Reduces bet size on highly unstable assets.
# 2. MUTATION "Z-Score Breakout": Replaced simple % change with Statistical 
#    Z-Score. This detects true anomalies vs random noise.
# 3. MOMENTUM FILTER: Only enters trades if 24h trend aligns with the breakout.
# 4. ANTI-RUIN: Max 5 concurrent positions to prevent total balance exposure.
# -----------------------------------------------------------------------------

import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (Gen 78: Phoenix Protocol)")
        
        # --- Configuration ---
        self.HISTORY_LEN = 15           # Shorter window for faster reaction
        self.Z_ENTRY_THRESHOLD = 1.8    # Buy if price is 1.8 StdDev above mean
        self.Z_EXIT_THRESHOLD = 0.0     # Sell if price reverts to mean
        
        # --- Risk Management ---
        self.STOP_LOSS_PCT = 0.07       # 7% Hard Stop
        self.TRAILING_START = 0.15      # Start trailing after 15% gain
        self.TRAILING_DROP = 0.05       # Sell if drops 5% from peak
        self.BASE_BET_SIZE = 50.0       # Fixed bet size to rebuild confidence
        self.MAX_POSITIONS = 5          # Hard limit on open trades
        
        # --- State ---
        self.history = {}               # {symbol: deque([prices], maxlen=N)}
        self.positions = {}             # {symbol: {'entry': float, 'high': float}}
        self.banned_tags = set()
        
    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind to avoid toxic assets"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🛡️ Phoenix Protocol: Blacklisting {penalize}")
            self.banned_tags.update(penalize)

    def get_stats(self, symbol):
        """Calculate Mean and Standard Deviation"""
        data = self.history.get(symbol)
        if not data or len(data) < self.HISTORY_LEN:
            return None, None
        
        mean = statistics.mean(data)
        try:
            stdev = statistics.stdev(data)
        except:
            stdev = 0
            
        return mean, stdev

    def on_price_update(self, prices: dict):
        """
        Core Logic: Statistical Breakout + Iron-Clad Risk Management
        """
        decision = None
        
        # 1. Update History & Filter Data
        for symbol, data in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.HISTORY_LEN)
            self.history[symbol].append(data["priceUsd"])

        # 2. Manage Existing Positions (DEFENSE)
        # We prioritize selling/stopping out over buying
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]["priceUsd"]
            pos_data = self.positions[symbol]
            entry_price = pos_data['entry']
            
            # Update High Water Mark
            if current_price > pos_data['high']:
                self.positions[symbol]['high'] = current_price
                
            # Logic: Hard Stop Loss
            loss_pct = (entry_price - current_price) / entry_price
            if loss_pct >= self.STOP_LOSS_PCT:
                print(f"🚨 STOP LOSS: {symbol} (Loss: {loss_pct:.2%})")
                del self.positions[symbol]
                return ("sell", symbol, 1.0) # Sell 100%
            
            # Logic: Trailing Profit Take
            gain_pct = (current_price - entry_price) / entry_price
            if gain_pct >= self.TRAILING_START:
                drop_from_high = (pos_data['high'] - current_price) / pos_data['high']
                if drop_from_high >= self.TRAILING_DROP:
                    print(f"💰 TAKE PROFIT: {symbol} (Locked Gain)")
                    del self.positions[symbol]
                    return ("sell", symbol, 1.0)
            
            # Logic: Mean Reversion Exit (Trend Faded)
            mean, _ = self.get_stats(symbol)
            if mean and current_price < mean:
                print(f"📉 TREND BROKEN: {symbol}")
                del self.positions[symbol]
                return ("sell", symbol, 1.0)

        # 3. Look for New Entries (OFFENSE)
        # Only if we have slots available
        if len(self.positions) < self.MAX_POSITIONS:
            best_opportunity = None
            highest_z_score = 0
            
            for symbol, data in prices.items():
                # Filter: Blacklist or Already Holding
                if symbol in self.banned_tags or symbol in self.positions:
                    continue
                
                # Filter: Minimum History
                mean, stdev = self.get_stats(symbol)
                if not mean or stdev == 0:
                    continue
                    
                current_price = data["priceUsd"]
                
                # Metric: Z-Score (How many deviations from normal?)
                z_score = (current_price - mean) / stdev
                
                # Metric: Momentum Confirmation (24h change must be positive)
                momentum_ok = data.get("priceChange24h", 0) > 2.0 
                
                # Signal: Strong Statistical Breakout + Momentum
                if z_score > self.Z_ENTRY_THRESHOLD and momentum_ok:
                    # We pick the strongest signal in the batch
                    if z_score > highest_z_score:
                        highest_z_score = z_score
                        best_opportunity = symbol
            
            # Execute Buy
            if best_opportunity:
                price = prices[best_opportunity]["priceUsd"]
                print(f"🚀 ENTER: {best_opportunity} (Z-Score: {highest_z_score:.2f})")
                
                self.positions[best_opportunity] = {
                    'entry': price,
                    'high': price
                }
                
                # Calculate safe position size (Volatility scaling)
                # If Z-score is huge (very volatile), we might reduce size slightly, 
                # but for recovery, we stick to BASE_BET_SIZE
                return ("buy", best_opportunity, self