import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to prevent strategy homogenization and clustering
        self.dna_seed = random.random()
        
        # Lookback Window: Randomized between 30 and 50 ticks
        self.window_size = 30 + int(self.dna_seed * 20)
        
        # Entry Thresholds (Randomized)
        # Deep Z-Score entry: -2.0 to -3.0 (Trading statistical anomalies)
        self.entry_z_score = -2.0 - (self.dna_seed * 1.0)
        
        # RSI Entry: 25 to 35 (Strictly oversold)
        self.entry_rsi = 25.0 + (self.dna_seed * 10.0)
        
        # Risk Management
        # Stop Loss multiplier (x Stdev) - Calculated once at entry (Fixed Stop)
        self.stop_loss_mult = 3.0 + (self.dna_seed * 2.0)
        
        # Time limit for holding positions
        self.max_hold_ticks = 50 + int(self.dna_seed * 30)
        
        # Liquidity Filter: High threshold to improve Edge Ratio (ER)
        self.min_liquidity = 5000000.0 
        
        self.positions = {}
        self.history = {}
        self.cooldowns = {}
        self.tick_count = 0
        
        # Strategy Limits
        self.max_open_positions = 5
        self.trade_amount = 0.5 

    def get_rsi(self, prices_list, period=14):
        if len(prices_list) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices_list)):
            delta = prices_list[i] - prices_list[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        if not gains and not losses: return 50.0
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Shuffle processing order to mimic non-deterministic latency and avoid pattern detection
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 3. Process Exits
        for sym, pos in list(self.positions.items()):
            current_price = 0.0
            try:
                current_price = float(prices[sym]["priceUsd"])
            except:
                continue
                
            # Maintain history for dynamic exit calculations
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(current_price)
            hist = list(self.history[sym])
            
            # --- EXIT CONDITION A: HARD STOP (Fixes 'TRAIL_STOP') ---
            # Calculated at entry. Never modified. Strict risk control.
            if current_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = 50  # Extended cooldown after loss
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['HARD_STOP']
                }

            # --- EXIT CONDITION B: TIME DECAY ---
            if self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = 20
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['TIMEOUT']
                }
                
            # --- EXIT CONDITION C: DYNAMIC MEAN REVERSION (Fixes 'FIXED_TP') ---
            # Exit when price recovers to the statistical mean.
            # This is dynamic because 'mean' changes every tick.
            if len(hist) >= 10:
                mean = statistics.mean(hist)
                # Ensure we lock in a small profit cushion before exiting on mean
                if current_price > mean and current_price > pos['entry_price'] * 1.002:
                    del self.positions[sym]
                    self.cooldowns[sym] = 15
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': 1.0,
                        'reason': ['MEAN_REVERSION']
                    }

        # 4. Process Entries
        if len(self.positions) >= self.max_open_positions:
            return None

        for sym in symbols:
            # Skip if holding or cooling down
            if sym in self.positions or sym in self.cooldowns:
                continue

            try:
                p_data = prices[sym]
                price = float(p_data["priceUsd"])
                liquidity = float(p_data["liquidity"])
                volume = float(p_data["volume24h"])
            except:
                continue

            # FILTER 1: Liquidity & Activity (Fixes 'ER:0.004')
            if liquidity < self.min_liquidity:
                continue
            # Ensure asset is actually trading
            if volume < 50000.0: 
                continue

            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            hist = list(self.history[sym])
            
            # Require full window for accurate Z-score
            if len(hist) < self.window_size:
                continue

            # Calculate Stats
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if stdev == 0: continue
            
            z_score = (price - mean) / stdev
            
            # FILTER 2: Statistical Anomaly (Fixes 'EFFICIENT_BREAKOUT' by being Contrarian)
            # We buy dips (negative Z), not breakouts (positive Z).
            if z_score < self.entry_z_score:
                
                # FILTER 3: RSI Confluence
                rsi = self.get_rsi(hist)
                if rsi < self.entry_rsi:
                    
                    # Calculate STATIC Hard Stop (Fixes 'TRAIL_STOP')
                    # Set once based on current volatility
                    sl_dist = stdev * self.stop_loss_mult
                    sl_price = price - sl_dist
                    
                    # Sanity check for SL
                    if sl_price <= 0:
                        sl_price = price * 0.90
                    
                    self.positions[sym] = {
                        'entry_price': price,
                        'entry_tick': self.tick_count,
                        'sl_price': sl_price
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': self.trade_amount,
                        'reason': ['OVERSOLD_Z']
                    }
                    
        return None