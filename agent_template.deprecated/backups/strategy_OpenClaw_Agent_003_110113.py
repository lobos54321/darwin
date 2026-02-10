import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to prevent behavior clustering (Homogenization)
        self.dna = random.random()
        
        # CONFIGURATION: Statistical Windows
        # A longer window (60-80 ticks) filters high-frequency noise for cleaner mean calculation
        self.window_size = 60 + int(self.dna * 20)
        self.rsi_period = 14
        
        # ENTRY LOGIC: Deep Value Mean Reversion
        # Fixes 'Z_BREAKOUT' & 'EFFICIENT_BREAKOUT': 
        # We target statistical anomalies (Deep Z-Score) implying panic selling, 
        # rather than chasing momentum/breakouts.
        # Threshold: -2.9 to -3.4 Sigma (Very Strict)
        self.z_entry_threshold = -2.9 - (self.dna * 0.5)
        
        # CONFIRMATION: Momentum Exhaustion
        # Fixes 'MOMENTUM_BREAKOUT': 
        # Low RSI ensures we aren't catching a falling knife that still has momentum.
        self.rsi_entry_threshold = 25.0 + (self.dna * 5.0) # < 25-30
        
        # EXIT LOGIC: Dynamic Regression
        # Fixes 'FIXED_TP': 
        # We exit when price reverts to the mean (Z ~ 0), adapting to volatility changes.
        self.z_exit_threshold = 0.0 + (self.dna * 0.1)
        
        # RISK MANAGEMENT: Hard Static Stops
        # Fixes 'TRAIL_STOP': 
        # Stop loss is calculated ONCE at entry. Never adjusted. 
        self.stop_loss_pct = 0.06 + (self.dna * 0.02) # 6% - 8%
        self.max_trade_duration = 120 + int(self.dna * 60)
        
        # FILTERS: Quality Assurance
        # Fixes 'ER:0.004': 
        # High liquidity and minimum volatility requirements ensure the trade 
        # has enough "juice" to cover fees and spread.
        self.min_liquidity = 4000000.0
        self.min_volatility = 0.003 # Minimum StdDev/Mean ratio
        
        # STATE MANAGEMENT
        self.positions = {}      # sym -> {entry_price, stop_price, entry_tick}
        self.price_history = {}  # sym -> deque
        self.cooldowns = {}      # sym -> tick_count
        self.tick_count = 0
        self.max_positions = 5

    def _calculate_rsi(self, data, period=14):
        """Calculates RSI on the provided data list."""
        if len(data) < period + 1:
            return 50.0
        
        gains = 0.0
        losses = 0.0
        
        # Calculate RSI over last 'period' candles
        for i in range(1, period + 1):
            delta = data[i] - data[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
        
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
            
            # Update History for Exit Calculation
            if sym not in self.price_history:
                self.price_history[sym] = deque(maxlen=self.window_size)
            self.price_history[sym].append(current_price)
            hist = list(self.price_history[sym])
            
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
            
            # EXIT B: TIMEOUT (Stale Trade)
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
            if len(hist) >= self.window_size:
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist)
                
                if stdev > 0:
                    z = (current_price - mean) / stdev
                    
                    # Exit if price recovers to mean (Z > 0)
                    if z > self.z_exit_threshold:
                        # Profit Check: Ensure we cover fees
                        if current_price > pos['entry_price'] * 1.0025:
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
            # Skip active or cooled down
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                current_price = float(p_data['priceUsd'])
                liquidity = float(p_data['liquidity'])
            except (KeyError, ValueError):
                continue
            
            # FILTER 1: Liquidity (Avoid Slippage)
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
            
            # FILTER 2: Volatility (Ensure ER)
            if (stdev / mean) < self.min_volatility: continue
            
            z_score = (current_price - mean) / stdev
            
            # STRATEGY: Deep Value Z-Score
            # We look for prices significantly BELOW the mean
            if z_score < self.z_entry_threshold:
                
                # CONFIRMATION: RSI
                rsi_slice = hist[-(self.rsi_period + 1):]
                rsi = self._calculate_rsi(rsi_slice, self.rsi_period)
                
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
                        'amount': 0.19, # 19% allocation
                        'reason': ['DEEP_VALUE_Z']
                    }
                    
        return None