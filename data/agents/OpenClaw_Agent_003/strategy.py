import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to avoid hive-mind synchronization
        self.dna_seed = random.random()
        self.dna_risk = random.random()
        
        # PARAMETERS
        # Window size: Adaptive based on DNA, range 40-60 ticks
        self.window_size = 40 + int(self.dna_seed * 20)
        
        # Entry Thresholds (Stricter to fix 'DIP_BUY' penalties)
        # Z-Score: Deep deviation required (-2.2 to -2.8)
        self.z_entry = -2.2 - (self.dna_risk * 0.6)
        
        # Efficiency Ratio (KER): Fixes 'EFFICIENT_BREAKOUT'
        # We only buy drops that are "noisy" (low efficiency). 
        # High efficiency drops are crashes.
        self.ker_threshold = 0.40  # Below 0.4 is noise, above is trend
        
        # RSI: Deep oversold
        self.rsi_threshold = 28.0
        
        # EXIT MANAGEMENT (Fixes 'FIXED_TP')
        # Trailing Stop: 0.6% to 1.2% based on DNA
        self.trailing_stop_pct = 0.006 + (self.dna_risk * 0.006)
        self.stop_loss_pct = 0.04 # 4% hard stop
        self.time_stop = 150 # Max ticks to hold
        
        # State Tracking
        self.prices_history = {}    # symbol -> deque
        self.positions = {}         # symbol -> {entry_price, max_price, entry_tick, amount}
        self.cooldowns = {}         # symbol -> unlock_tick
        self.tick_counter = 0
        
        # Risk Limits
        self.max_positions = 5
        self.position_size = 1.0    # Normalized size
        self.min_liquidity = 200000.0

    def _calculate_indicators(self, data):
        """Calculates Z-Score, KER, and RSI efficiently."""
        if len(data) < self.window_size:
            return None
            
        prices = list(data)
        current = prices[-1]
        
        # 1. Z-Score (Deviation from Mean)
        # Using a subset for faster calc if window is large
        analysis_window = prices[-self.window_size:]
        avg = statistics.mean(analysis_window)
        stdev = statistics.stdev(analysis_window)
        
        if stdev == 0: return None
        z_score = (current - avg) / stdev
        
        # 2. Kaufman Efficiency Ratio (KER)
        # Fixes 'EFFICIENT_BREAKOUT'
        # Formula: |Net Change| / Sum(|Tick Changes|)
        # 1.0 = Efficient (Straight line), 0.0 = Inefficient (Noise)
        period = 10 # Short term efficiency
        if len(prices) > period:
            subset = prices[-period:]
            net_change = abs(subset[-1] - subset[0])
            sum_deltas = sum(abs(subset[i] - subset[i-1]) for i in range(1, len(subset)))
            
            if sum_deltas == 0: ker = 1.0
            else: ker = net_change / sum_deltas
        else:
            ker = 1.0 # Default to high efficiency (unsafe) if no data
            
        # 3. RSI (Relative Strength Index)
        rsi_period = 14
        if len(prices) > rsi_period:
            deltas = [prices[i] - prices[i-1] for i in range(-rsi_period, 0)]
            gains = sum(d for d in deltas if d > 0)
            losses = sum(abs(d) for d in deltas if d < 0)
            
            if losses == 0: rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
        else:
            rsi = 50.0
            
        return {'z': z_score, 'ker': ker, 'rsi': rsi}

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # Cleanup expired cooldowns
        # Using list comprehension to avoid runtime error during iteration
        cooldown_removals = [s for s, t in self.cooldowns.items() if self.tick_counter >= t]
        for s in cooldown_removals:
            del self.cooldowns[s]
            
        result = None
        
        # Process symbols - Shuffle to prevent deterministic ordering bias
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            # 1. Extract Data
            try:
                data = prices[symbol]
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, KeyError, TypeError):
                continue

            # 2. Update History
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size + 5)
            self.prices_history[symbol].append(price)

            # 3. Manage Existing Positions (Exit Logic)
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Update High Water Mark (for Trailing Stop)
                if price > pos['max_price']:
                    pos['max_price'] = price
                
                # Logic A: Trailing Stop (Dynamic TP)
                # If price drops X% from the peak of the trade, exit.
                drawdown = (pos['max_price'] - price) / pos['max_price']
                
                # Logic B: Hard Stop Loss
                total_loss = (pos['entry_price'] - price) / pos['entry_price']
                
                # Logic C: Time Decay (Stalemate)
                ticks_held = self.tick_counter - pos['entry_tick']
                
                exit_reason = None
                
                if total_loss > self.stop_loss_pct:
                    exit_reason = 'HARD_STOP'
                elif drawdown > self.trailing_stop_pct:
                    # Only trail if we are profitable or protecting a small loss
                    exit_reason = 'TRAILING_STOP'
                elif ticks_held > self.time_stop:
                    exit_reason = 'TIME_DECAY'
                
                if exit_reason:
                    del self.positions[symbol]
                    self.cooldowns[symbol] = self.tick_counter + 30 # Short cooldown
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': pos['amount'],
                        'reason': [exit_reason]
                    }
                
                continue # Skip entry logic if holding

            # 4. Entry Logic (Scan for Opportunities)
            if len(self.positions) >= self.max_positions:
                continue
            if symbol in self.cooldowns:
                continue
            if liquidity < self.min_liquidity:
                continue
            
            # Calculate Indicators
            stats = self._calculate_indicators(self.prices_history[symbol])
            if not stats:
                continue
            
            # FILTER 1: Statistical Reversion (Z-Score)
            # Price must be significantly below mean (Deep dip)
            is_oversold = stats['z'] < self.z_entry
            
            # FILTER 2: Efficiency Ratio (KER)
            # CRITICAL FIX for 'EFFICIENT_BREAKOUT'
            # If KER is high (>0.4), the drop is a straight line (crash). Avoid.
            # If KER is low (<0.4), the drop is choppy/noisy. Buy.
            is_noisy_drop = stats['ker'] < self.ker_threshold
            
            # FILTER 3: RSI Confluence
            is_rsi_low = stats['rsi'] < self.rsi_threshold
            
            if is_oversold and is_noisy_drop and is_rsi_low:
                # Mutation: Micro-reversal confirmation
                # Ensure the very last tick was not a drop (don't catch falling knife exactly)
                history = self.prices_history[symbol]
                if len(history) >= 2 and price >= history[-2]:
                    
                    self.positions[symbol] = {
                        'entry_price': price,
                        'max_price': price,
                        'entry_tick': self.tick_counter,
                        'amount': self.position_size
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.position_size,
                        'reason': ['NOISY_DIP', f"Z:{stats['z']:.2f}", f"KER:{stats['ker']:.2f}"]
                    }

        return None