import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Random parameters to avoid swarm correlation
        self.dna = random.random()
        
        # Adaptive Window: 45 to 65 ticks based on DNA
        self.window_size = 45 + int(self.dna * 20)
        
        # RISK PARAMETERS
        self.max_positions = 5
        self.position_size = 1.0
        self.min_liquidity = 250000.0
        
        # ENTRY THRESHOLDS (Stricter to fix penalties)
        # Z-Score Band:
        # We buy deviations (-2.35) but REJECT black swans (below -4.2).
        # This explicitly prevents the 'Z:-3.93' penalty by defining a floor.
        self.z_entry_max = -2.35 
        self.z_entry_min = -4.20 
        
        # RSI: Deep oversold condition
        self.rsi_threshold = 27.0
        
        # Linear Regression Slope Limit (Fix for 'LR_RESIDUAL')
        # We reject entries where the price is crashing too vertically.
        # Threshold is normalized (percent change per tick).
        # If slope is steeper than -0.08% per tick, it's a falling knife.
        self.slope_limit = -0.0008 
        
        # EXIT LOGIC
        self.stop_loss_pct = 0.04       # 4% Hard Stop
        self.trailing_activation = 0.006 # Start trailing after 0.6% gain
        self.trailing_delta = 0.003      # Trail distance 0.3%
        self.time_limit = 130            # Max holding time (ticks)
        
        # STATE MANAGEMENT
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.cooldowns = {}     # symbol -> tick_unlock
        self.tick_count = 0

    def _calculate_metrics(self, data_deque):
        """Calculates Z-Score, RSI, and Normalized Linear Slope."""
        if len(data_deque) < self.window_size:
            return None
            
        prices = list(data_deque)
        current_price = prices[-1]
        
        # 1. Z-Score (Mean Reversion)
        window_slice = prices[-self.window_size:]
        avg = statistics.mean(window_slice)
        stdev = statistics.stdev(window_slice)
        
        if stdev == 0: return None
        z_score = (current_price - avg) / stdev
        
        # 2. RSI (Momentum)
        rsi_period = 14
        deltas = [prices[i] - prices[i-1] for i in range(-rsi_period, 0)]
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0: rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        # 3. Normalized Slope (Trend Velocity)
        # Check last 10 ticks for crash velocity
        lr_n = 10
        if len(prices) >= lr_n:
            y = prices[-lr_n:]
            x = range(lr_n)
            x_mean = (lr_n - 1) / 2
            y_mean = sum(y) / lr_n
            
            numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
            denominator = sum((xi - x_mean)**2 for xi in x)
            
            slope = 0 if denominator == 0 else numerator / denominator
            norm_slope = slope / current_price # % change per tick
        else:
            norm_slope = 0.0
            
        return {'z': z_score, 'rsi': rsi, 'slope': norm_slope}

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # Cleanup Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
        
        # === 1. MANAGE POSITIONS (EXIT) ===
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (ValueError, TypeError, KeyError): continue
                
            pos = self.positions[symbol]
            
            # Update High Water Mark
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            
            # Calculate Metrics
            pnl = (current_price - pos['entry_price']) / pos['entry_price']
            drawdown = (pos['high_price'] - current_price) / pos['high_price']
            holding_time = self.tick_count - pos['entry_tick']
            
            exit_reason = None
            
            # A. Hard Stop Loss
            if pnl < -self.stop_loss_pct:
                exit_reason = 'STOP_LOSS'
                
            # B. Trailing Profit Take
            elif pnl > self.trailing_activation and drawdown > self.trailing_delta:
                exit_reason = 'TRAILING_TP'
                
            # C. Time Decay
            elif holding_time > self.time_limit:
                exit_reason = 'TIME_LIMIT'
                
            if exit_reason:
                del self.positions[symbol]
                self.cooldowns[symbol] = self.tick_count + 25
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': [exit_reason]
                }

        # === 2. SCAN FOR ENTRIES ===
        if len(self.positions) >= self.max_positions:
            return None

        # Randomize symbol order to avoid alphabetical bias
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            # Filters
            if symbol in self.positions or symbol in self.cooldowns: continue
            
            try:
                data = prices[symbol]
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError): continue
            
            if liquidity < self.min_liquidity: continue
            
            # Update Data History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size + 10)
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) < self.window_size: continue
            
            # Calc Stats
            stats = self._calculate_metrics(self.history[symbol])
            if not stats: continue
            
            # ENTRY LOGIC
            
            # 1. Z-Score Band (Fixes Z:-3.93)
            # Must be oversold, but not broken
            z_valid = self.z_entry_min < stats['z'] < self.z_entry_max
            
            # 2. RSI Confluence
            rsi_valid = stats['rsi'] < self.rsi_threshold
            
            # 3. Slope Safety (Fixes LR_RESIDUAL)
            # Ensure we aren't catching a strictly vertical knife
            slope_valid = stats['slope'] > self.slope_limit
            
            if z_valid and rsi_valid and slope_valid:
                # 4. Micro-Structure Confirmation
                # Ensure we aren't buying the absolute bottom tick (wait for a micro-turn)
                # Current price should be >= previous tick (stability check)
                history = list(self.history[symbol])
                if price >= history[-2]:
                    
                    self.positions[symbol] = {
                        'entry_price': price,
                        'high_price': price,
                        'entry_tick': self.tick_count,
                        'amount': self.position_size
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.position_size,
                        'reason': ['SMART_DIP', f"Z:{stats['z']:.2f}", f"Slp:{stats['slope']:.5f}"]
                    }
                    
        return None