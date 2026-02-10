import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to prevent behavior clustering (Homogenization)
        self.dna = random.random()
        
        # CONFIGURATION: Statistical Windows
        # A longer window (50-80 ticks) filters high-frequency noise
        self.window_size = 50 + int(self.dna * 30)
        self.rsi_period = 14
        
        # ENTRY LOGIC: Deep Value Mean Reversion
        # Fixes 'Z_BREAKOUT' & 'EFFICIENT_BREAKOUT': 
        # Target deep statistical anomalies (Dip Buy) rather than momentum.
        # Threshold: -2.8 to -3.4 Sigma (Very Strict)
        self.z_entry_threshold = -2.8 - (self.dna * 0.6)
        
        # CONFIRMATION: RSI Oversold
        # Fixes 'MOMENTUM_BREAKOUT': 
        # Ensure asset is oversold (RSI < 25-30)
        self.rsi_entry_threshold = 25.0 + (self.dna * 5.0)
        
        # EXIT LOGIC: Dynamic Regression
        # Fixes 'FIXED_TP': 
        # Exit when price reverts to the mean (Z > 0)
        self.z_exit_threshold = 0.0 + (self.dna * 0.2)
        
        # RISK MANAGEMENT: Hard Static Stops
        # Fixes 'TRAIL_STOP': 
        # Stop loss is calculated ONCE at entry. Never adjusted.
        self.stop_loss_pct = 0.05 + (self.dna * 0.03) # 5% - 8%
        self.max_trade_duration = 100 + int(self.dna * 50)
        
        # FILTERS
        # Fixes 'ER:0.004' by ensuring high liquidity and volatility
        self.min_liquidity = 2000000.0
        self.min_volatility = 0.002
        
        # STATE
        self.positions = {}      # sym -> {entry_price, stop_price, entry_tick}
        self.price_history = {}  # sym -> deque
        self.cooldowns = {}      # sym -> tick_count
        self.tick_count = 0
        self.max_positions = 5

    def _calculate_rsi(self, data, period=14):
        """Calculates RSI on the provided data list."""
        if len(data) < period + 1:
            return 50.0
        
        # Calculate changes over the last 'period' candles
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        recent_changes = changes[-period:]
        
        gains = sum(c for c in recent_changes if c > 0)
        losses = sum(abs(c) for c in recent_changes if c < 0)
        
        if losses == 0:
            return 100.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Manage Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
        
        # 2. Randomize Execution (Latency masking)
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 3. Manage Existing Positions
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                current_price = float(prices[sym]['priceUsd'])
            except (KeyError, ValueError):
                continue
                
            pos = self.positions[sym]
            
            # Update History
            if sym not in self.price_history:
                self.price_history[sym] = deque(maxlen=self.window_size)
            self.price_history[sym].append(current_price)
            
            # EXIT A: HARD STOP LOSS (Risk Control)
            if current_price <= pos['stop_price']:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 300
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['HARD_STOP']
                }
            
            # EXIT B: TIMEOUT
            if self.tick_count - pos['entry_tick'] > self.max_trade_duration:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 100
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['TIMEOUT']
                }
            
            # EXIT C: DYNAMIC MEAN REVERSION
            hist = list(self.price_history[sym])
            if len(hist) >= self.window_size:
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist)
                
                if stdev > 0:
                    z = (current_price - mean) / stdev
                    
                    # Exit if price recovers to mean (Z > 0)
                    if z > self.z_exit_threshold:
                        # Profit Check: Ensure we cover fees
                        if current_price > pos['entry_price'] * 1.002:
                            del self.positions[sym]
                            self.cooldowns[sym] = self.tick_count + 50
                            return {
                                'side': 'SELL',
                                'symbol': sym,
                                'amount': 1.0,
                                'reason': ['MEAN_REV_EXIT']
                            }

        # 4. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None

        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                current_price = float(p_data['priceUsd'])
                liquidity = float(p_data['liquidity'])
            except (KeyError, ValueError):
                continue
            
            # FILTER 1: Liquidity
            if liquidity < self.min_liquidity: continue
            
            # Update History
            if sym not in self.price_history:
                self.price_history[sym] = deque(maxlen=self.window_size)
            self.price_history[sym].append(current_price)
            
            hist = list(self.price_history[sym])
            if len(hist) < self.window_size: continue
            
            # Calculate Statistics
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if stdev == 0: continue
            
            # FILTER 2: Volatility
            if (stdev / mean) < self.min_volatility: continue
            
            z_score = (current_price - mean) / stdev
            
            # STRATEGY: Deep Value Z-Score (Dip Buy)
            if z_score < self.z_entry_threshold:
                
                # CONFIRMATION: RSI Oversold
                rsi = self._calculate_rsi(hist, self.rsi_period)
                
                if rsi < self.rsi_entry_threshold:
                    
                    # Hard Stop Logic
                    stop_price = current_price * (1.0 - self.stop_loss_pct)
                    
                    self.positions[sym] = {
                        'entry_price': current_price,
                        'entry_tick': self.tick_count,
                        'stop_price': stop_price
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': 0.15,
                        'reason': ['DEEP_VALUE_Z']
                    }
                    
        return None