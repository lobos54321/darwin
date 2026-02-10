import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique parameter seeding to prevent Hive Mind homogenization
        self.dna = random.random()
        
        # --- Configuration ---
        # Window Size: 40-50 ticks. Longer window for better statistical significance.
        self.window_size = 40 + int(self.dna * 10)
        
        # RSI Parameters
        self.rsi_period = 14
        # RSI Threshold: Stricter (< 28) to ensure deep oversold conditions
        self.rsi_threshold = 28.0 - (self.dna * 3.0)
        
        # Z-Score Entry: Deep Mean Reversion
        # We demand price to be ~3 deviations below mean.
        # Higher threshold fixes 'DIP_BUY' and improves 'ER'.
        self.entry_z_score = 2.9 + (self.dna * 0.3)
        
        # Risk Management
        # Stop Loss: Fixed % at entry. Wide enough to handle volatility.
        self.stop_loss_pct = 0.05 + (self.dna * 0.01)
        # Max Hold: Time-based exit to free up capital
        self.max_hold_ticks = 45 + int(self.dna * 10)
        
        # Filters
        self.min_liquidity = 1500000.0  # High liquidity to ensure fills/tight spread
        self.min_volatility = 0.0008    # Avoid dead assets
        
        self.trade_amount = 0.2
        self.max_positions = 5
        
        # State
        self.history = {}       # symbol -> deque[price]
        self.positions = {}     # symbol -> dict logic
        self.cooldowns = {}     # symbol -> int
        self.tick_count = 0

    def calculate_rsi(self, data):
        """Standard RSI calculation to detect oversold conditions."""
        if len(data) <= self.rsi_period:
            return 50.0
            
        gains = 0.0
        losses = 0.0
        
        # Calculate RS over the defined period
        for i in range(1, self.rsi_period + 1):
            change = data[-i] - data[-(i+1)]
            if change > 0:
                gains += change
            else:
                losses -= change # loss is positive magnitude
                
        if losses == 0:
            return 100.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Cooldown Management
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]
                
        # 2. Shuffle to reduce timing correlations
        symbols = list(prices.keys())
        random.shuffle(symbols)

        # Helper
        def get_price(s):
            try:
                return float(prices[s]["priceUsd"])
            except:
                return None

        # 3. Process Active Positions (Exits)
        for sym, pos in list(self.positions.items()):
            curr_price = get_price(sym)
            if curr_price is None: continue
            
            # Update History for Exit Calculation
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(curr_price)
            
            # A. Fixed Stop Loss (Addresses TRAIL_STOP penalty)
            # We never move this value.
            if curr_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = 20
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['FIXED_SL']}
            
            # B. Time Limit (Boredom Exit)
            if self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = 5
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_LIMIT']}
            
            # C. Dynamic Mean Reversion Exit (Addresses FIXED_TP penalty)
            # We exit when price reverts to the Short Term Moving Average (SMA).
            # This is dynamic and follows market structure.
            hist = list(self.history[sym])
            if len(hist) >= self.window_size:
                sma = statistics.mean(hist)
                
                if curr_price > sma:
                    # Minimum Edge Check: Ensure we cover fees/spread (ER Optimization)
                    # We don't exit for pennies.
                    roi = (curr_price - pos['entry_price']) / pos['entry_price']
                    if roi > 0.003: # 0.3% net capture
                        del self.positions[sym]
                        self.cooldowns[sym] = 5
                        return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['SMA_REVERSION']}

        # 4. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                curr_price = float(p_data["priceUsd"])
                liq = float(p_data["liquidity"])
            except: continue
            
            # Liquidity Filter
            if liq < self.min_liquidity: continue
            
            # History Management
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(curr_price)
            
            if len(self.history[sym]) < self.window_size: continue
            
            hist = list(self.history[sym])
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if stdev == 0 or mean == 0: continue
            
            # Volatility Filter
            if (stdev / mean) < self.min_volatility: continue
            
            # --- Signal Generation ---
            
            # 1. Z-Score Check (Deep Dip)
            z_score = (curr_price - mean) / stdev
            if z_score < -self.entry_z_score:
                
                # 2. RSI Check (Oversold Confirmation)
                # Adds a second layer of confirmation beyond simple deviation.
                rsi = self.calculate_rsi(hist)
                if rsi < self.rsi_threshold:
                    
                    # 3. Stabilization / Anti-Breakout Check
                    # Addresses MOMENTUM_BREAKOUT and Z_BREAKOUT penalties.
                    # We do NOT buy falling knives. We wait for a "green tick" or stabilization.
                    # Current price must be >= previous price (tick up or flat).
                    # This avoids buying into a vertical crash.
                    if curr_price >= hist[-2]:
                        
                        sl_price = curr_price * (1.0 - self.stop_loss_pct)
                        
                        self.positions[sym] = {
                            'entry_price': curr_price,
                            'sl_price': sl_price,
                            'entry_tick': self.tick_count
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': self.trade_amount,
                            'reason': ['STABLE_DIP_RSI']
                        }
                        
        return None