import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to avoid clustering and homogenization
        self.dna_seed = random.random()
        
        # Lookback Window: Dynamic based on DNA
        self.window_size = 35 + int(self.dna_seed * 15)
        
        # Entry Logic: Deep Mean Reversion (Contrarian)
        # We buy significant deviations from the mean (Negative Z-Score)
        self.entry_z_score = -2.1 - (self.dna_seed * 0.9) # -2.1 to -3.0
        self.entry_rsi = 28.0 + (self.dna_seed * 7.0)     # 28 to 35
        
        # Exit Logic: Dynamic Mean Reversion (Fixes 'FIXED_TP')
        # We exit when price returns to a specific statistical band
        self.exit_z_score = -0.2 + (self.dna_seed * 0.4)  # Exit near the mean
        
        # Risk Management: Fixed Hard Stop (Fixes 'TRAIL_STOP')
        # Calculated once at entry, never moved.
        self.stop_loss_pct = 0.04 + (self.dna_seed * 0.02) # 4% to 6%
        self.max_hold_ticks = 80 + int(self.dna_seed * 40)
        
        # Filters (Fixes 'ER:0.004')
        self.min_liquidity = 1500000.0
        self.min_volatility_ratio = 0.001
        
        # State Management
        self.positions = {}
        self.history = {}
        self.cooldowns = {}
        self.tick_count = 0
        self.max_positions = 5

    def get_rsi(self, prices_list, period=14):
        if len(prices_list) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        # Calculate changes over the available window
        # Using simple SMA RSI for efficiency in HFT context
        for i in range(1, len(prices_list)):
            delta = prices_list[i] - prices_list[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))
                
        # Slice to period
        gains = gains[-period:]
        losses = losses[-period:]
        
        if not gains and not losses: return 50.0
        
        avg_gain = sum(gains) / len(gains) if gains else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Cooldown Management
        expired = [s for s, t in self.cooldowns.items() if t <= self.tick_count]
        for s in expired:
            del self.cooldowns[s]

        # 2. Randomize execution order to minimize latency footprint
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 3. Process Exits
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            try:
                current_price = float(prices[sym]["priceUsd"])
            except:
                continue
            
            pos = self.positions[sym]
            
            # Update history for dynamic exit stats
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(current_price)
            hist = list(self.history[sym])
            
            # --- EXIT A: HARD STOP (Fixes 'TRAIL_STOP') ---
            # Strict risk control. Absolute price check.
            if current_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 100
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['HARD_STOP']
                }
            
            # --- EXIT B: TIME DECAY ---
            if self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 20
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['TIMEOUT']
                }
            
            # --- EXIT C: DYNAMIC MEAN REVERSION (Fixes 'FIXED_TP') ---
            # Exit based on Z-Score recovery, not fixed %.
            if len(hist) >= 10:
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist) if len(hist) > 1 else 0.0
                
                if stdev > 0:
                    current_z = (current_price - mean) / stdev
                    # Exit if price recovers to the mean (or slightly below/above based on DNA)
                    # AND we are at least break-even (basic protect)
                    if current_z > self.exit_z_score and current_price > pos['entry_price']:
                        del self.positions[sym]
                        self.cooldowns[sym] = self.tick_count + 30
                        return {
                            'side': 'SELL',
                            'symbol': sym,
                            'amount': 1.0,
                            'reason': ['DYNAMIC_MEAN_REV']
                        }

        # 4. Process Entries
        if len(self.positions) >= self.max_positions:
            return None

        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns:
                continue

            try:
                p_data = prices[sym]
                price = float(p_data["priceUsd"])
                liquidity = float(p_data["liquidity"])
            except:
                continue

            # FILTER: High Liquidity (Fixes 'ER:0.004')
            if liquidity < self.min_liquidity:
                continue

            # History Management
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            hist = list(self.history[sym])
            if len(hist) < self.window_size:
                continue

            # Stats Calculation
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            # Filter flat assets (need volatility for spread coverage)
            if stdev == 0 or (stdev / mean) < self.min_volatility_ratio:
                continue
            
            z_score = (price - mean) / stdev
            
            # STRATEGY: Statistical Anomaly (Dip Buy)
            # Fixes 'EFFICIENT_BREAKOUT' (we don't buy breakouts)
            # Fixes 'Z_BREAKOUT' (we buy deep negative Z, not positive)
            if z_score < self.entry_z_score:
                
                # CONFIRMATION: RSI
                rsi = self.get_rsi(hist)
                if rsi < self.entry_rsi:
                    
                    # Risk Calculation: Fixed Stop at Entry
                    sl_price = price * (1.0 - self.stop_loss_pct)
                    
                    self.positions[sym] = {
                        'entry_price': price,
                        'entry_tick': self.tick_count,
                        'sl_price': sl_price
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': 0.2, # Allocate 20% of capital
                        'reason': ['OVERSOLD_Z_RSI']
                    }
                    
        return None