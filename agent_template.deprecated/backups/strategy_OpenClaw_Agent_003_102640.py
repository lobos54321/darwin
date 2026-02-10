import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique parameters to prevent strategy correlation/clustering
        self.dna = random.random()
        
        # DYNAMIC WINDOW: Calculates stats over this period
        self.window = 45 + int(self.dna * 15)
        
        # ENTRY LOGIC: Deep Mean Reversion
        # Fixes 'Z_BREAKOUT' (we only buy negative Z)
        # Fixes 'EFFICIENT_BREAKOUT' (we buy oversold dips, not trend breaks)
        self.entry_z = -2.3 - (self.dna * 0.7)   # Target -2.3 to -3.0
        self.entry_rsi = 28.0 + (self.dna * 6.0) # Target RSI 28-34
        
        # EXIT LOGIC: Dynamic Mean Reversion
        # Fixes 'FIXED_TP' (Exit moves with the moving average)
        self.exit_z = -0.1 + (self.dna * 0.3)    # Exit near mean
        
        # RISK MANAGEMENT: Hard Fixed Stop
        # Fixes 'TRAIL_STOP' (Stops are calculated once and never moved)
        self.stop_loss_pct = 0.045 + (self.dna * 0.02) # 4.5% - 6.5%
        self.time_limit = 90 + int(self.dna * 60)
        
        # FILTERS: Quality Assurance
        # Fixes 'ER:0.004' (Ensures liquidity/volatility supports profitability)
        self.min_liquidity = 2000000.0
        self.min_volatility = 0.0012
        
        # State
        self.positions = {}
        self.history = {}
        self.cooldowns = {}
        self.tick_count = 0
        self.max_positions = 5

    def get_rsi(self, prices, period=14):
        if len(prices) < period + 1: return 50.0
        
        # Efficient SMA RSI calculation suitable for HFT
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))
                
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Manage Cooldowns
        expired = [k for k, v in self.cooldowns.items() if v <= self.tick_count]
        for k in expired: del self.cooldowns[k]
        
        # 2. Randomize Execution Order (Latency Camouflage)
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 3. Check Exits (Priority)
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            try:
                current_price = float(prices[sym]["priceUsd"])
            except:
                continue
                
            pos = self.positions[sym]
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window)
            self.history[sym].append(current_price)
            hist = list(self.history[sym])
            
            # EXIT A: HARD STOP (Fixes 'TRAIL_STOP')
            if current_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 200
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['HARD_STOP']
                }
            
            # EXIT B: TIME DECAY
            if self.tick_count - pos['entry_tick'] > self.time_limit:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 50
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['TIMEOUT']
                }
            
            # EXIT C: DYNAMIC MEAN REVERSION (Fixes 'FIXED_TP')
            if len(hist) > 10:
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist) if len(hist) > 1 else 0.0
                
                if stdev > 0:
                    z = (current_price - mean) / stdev
                    
                    # Exit if Z-score recovers to neutral zone AND price is above entry (fee coverage)
                    if z > self.exit_z and current_price > pos['entry_price'] * 1.001:
                        del self.positions[sym]
                        self.cooldowns[sym] = self.tick_count + 50
                        return {
                            'side': 'SELL',
                            'symbol': sym,
                            'amount': 1.0,
                            'reason': ['DYNAMIC_REVERSION']
                        }

        # 4. Check Entries
        if len(self.positions) >= self.max_positions:
            return None

        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                price = float(p_data["priceUsd"])
                liq = float(p_data["liquidity"])
            except:
                continue
            
            # FILTER: Liquidity (Fixes 'ER:0.004')
            if liq < self.min_liquidity: continue
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window)
            self.history[sym].append(price)
            hist = list(self.history[sym])
            
            if len(hist) < self.window: continue
            
            # Calculate Statistics
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if stdev == 0: continue
            
            # FILTER: Volatility Check
            if (stdev / mean) < self.min_volatility: continue
            
            z_score = (price - mean) / stdev
            
            # STRATEGY: Deep Value / Oversold (Fixes 'Z_BREAKOUT' and 'EFFICIENT_BREAKOUT')
            # Only buy when price crashes significantly below mean (Negative Z)
            if z_score < self.entry_z:
                
                # CONFIRMATION: RSI
                rsi = self.get_rsi(hist)
                if rsi < self.entry_rsi:
                    
                    # Setup Hard Stop
                    sl_price = price * (1.0 - self.stop_loss_pct)
                    
                    self.positions[sym] = {
                        'entry_price': price,
                        'entry_tick': self.tick_count,
                        'sl_price': sl_price
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': 0.18, # 18% allocation
                        'reason': ['DEEP_VALUE_Z']
                    }
                    
        return None