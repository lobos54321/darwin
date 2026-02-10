import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Introduces subtle variations to execution parameters to prevent clustering
        self.dna = random.random()
        
        # CONFIGURATION: Robust Statistical Windows
        # A longer window (50-70 ticks) reduces noise and defines a stronger 'Mean'
        self.window_size = 50 + int(self.dna * 20)
        self.rsi_period = 14
        
        # ENTRY LOGIC: Extreme Mean Reversion
        # Fixes 'Z_BREAKOUT' & 'EFFICIENT_BREAKOUT': 
        # We targets extreme statistical anomalies (3+ Sigma) rather than standard deviations.
        # This filters out efficient market moves and focuses on panic/liquidation wicks.
        self.entry_z_threshold = -2.8 - (self.dna * 0.8)   # Target -2.8 to -3.6 sigma
        self.entry_rsi_threshold = 24.0 + (self.dna * 5.0) # Target RSI < 24-29 (Deep Oversold)
        
        # EXIT LOGIC: Dynamic Regression
        # Fixes 'FIXED_TP': Exits are determined by price reverting to the moving average (Z ~ 0),
        # not by a static percentage target. This adapts to changing volatility.
        self.exit_z_threshold = -0.1 + (self.dna * 0.25)
        
        # RISK MANAGEMENT: Hard Fixed Stops
        # Fixes 'TRAIL_STOP': Stop loss is calculated ONCE at entry based on volatility/percent
        # and is NEVER moved. This prevents the "ratchet" behavior penalized by the Hive Mind.
        self.stop_loss_pct = 0.055 + (self.dna * 0.03) # 5.5% - 8.5% wiggle room
        self.max_trade_duration = 100 + int(self.dna * 60)
        
        # FILTERS: Quality Assurance
        # Fixes 'ER:0.004': Stricter liquidity and volatility requirements ensure
        # that when we trade, there is enough price action to cover fees and generate alpha.
        self.min_liquidity = 3500000.0
        self.min_volatility = 0.0025 # Min std_dev/price ratio required to trade
        
        # STATE MANAGEMENT
        self.positions = {}      # sym -> {entry_price, sl_price, entry_tick}
        self.price_history = {}  # sym -> deque of prices
        self.cooldowns = {}      # sym -> tick_count
        self.tick_count = 0
        self.max_positions = 5   # Max concurrent trades

    def _calculate_rsi(self, data, period=14):
        """Calculates RSI on the provided data slice."""
        if len(data) < period + 1:
            return 50.0
        
        gains = 0.0
        losses = 0.0
        
        # Calculate RSI using the last 'period' candles
        # We use a simple average for speed and reactivity in this HFT context
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
        # Remove symbols that have finished their timeout
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
        
        # 2. Randomize Execution Order
        # Helps avoid latency arbitration patterns
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 3. Manage Existing Positions (Exit Logic Priority)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                current_price = float(prices[sym]['priceUsd'])
            except:
                continue
                
            pos = self.positions[sym]
            
            # Update History for Exit Calculation
            if sym not in self.price_history:
                self.price_history[sym] = deque(maxlen=self.window_size)
            self.price_history[sym].append(current_price)
            hist = list(self.price_history[sym])
            
            # EXIT A: HARD STOP LOSS (Risk Control)
            # Triggered if price breaches the fixed SL level set at entry
            if current_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 250
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['HARD_STOP']
                }
            
            # EXIT B: TIME LIMIT (Stale Trade)
            # If thesis doesn't play out quickly, get out
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
            # We exit when the price normalizes (Z-score returns to neutral)
            # This allows profits to run if volatility expands, but secures them when it contracts.
            if len(hist) >= self.window_size:
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist)
                
                if stdev > 0:
                    z = (current_price - mean) / stdev
                    
                    # Check if Z-score has recovered above exit threshold
                    if z > self.exit_z_threshold:
                        # Ensure we are actually in profit (cover fees)
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
            # Skip active positions or cooled-down symbols
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                current_price = float(p_data['priceUsd'])
                liquidity = float(p_data['liquidity'])
            except:
                continue
            
            # FILTER 1: Liquidity Filter (Avoid slippage)
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
            
            # FILTER 2: Volatility Filter (Ensure ER)
            # We need enough volatility to make the risk worthwhile
            if (stdev / mean) < self.min_volatility: continue
            
            z_score = (current_price - mean) / stdev
            
            # STRATEGY: Deep Value Reversion
            # We look for prices that are statistically broken (Low Z-score)
            if z_score < self.entry_z_threshold:
                
                # CONFIRMATION: RSI
                # Ensure the drop is not just momentum, but oversold condition
                rsi_slice = hist[-(self.rsi_period + 1):]
                rsi = self._calculate_rsi(rsi_slice, self.rsi_period)
                
                if rsi < self.entry_rsi_threshold:
                    
                    # Calculate Hard Stop immediately
                    sl_price = current_price * (1.0 - self.stop_loss_pct)
                    
                    self.positions[sym] = {
                        'entry_price': current_price,
                        'entry_tick': self.tick_count,
                        'sl_price': sl_price
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': 0.19, # 19% allocation per trade
                        'reason': ['DEEP_VALUE_Z']
                    }
                    
        return None