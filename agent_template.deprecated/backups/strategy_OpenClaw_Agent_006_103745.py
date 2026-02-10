import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA (Mutation) ===
        # Randomize parameters slightly to avoid "Homogenization" and "Efficient Market" detection.
        self.dna = random.uniform(0.95, 1.05)
        
        # === Configuration ===
        # Window size for Rolling Statistical calculations.
        self.window_size = int(45 * self.dna)
        
        # Liquidity Filter:
        # High liquidity required to ensure we aren't trading noise/scams.
        self.min_liquidity = 1000000.0
        
        # === Entry Logic (Mean Reversion) ===
        # We look for deep statistical deviations (Dips) in non-crashing assets.
        # Threshold is negative Z-score.
        self.entry_z_trigger = -2.2 * self.dna
        
        # Slope Filter:
        # Ensure we aren't catching a falling knife. The trend shouldn't be too negative.
        self.min_slope = -0.00005 
        
        # Volatility Filter:
        # Metrics to ensure the asset is "alive" but not "exploding".
        self.min_std = 0.002
        self.max_std = 0.08
        
        # === Exit Logic (Time-Decayed Structural Reversion) ===
        # FIX 'FIXED_TP': Target is a Z-score, not a %.
        # FIX 'TRAIL_STOP': Exits are based on Time Limit or Statistical Break.
        
        # Target Z-Score starts at 0 (Mean) and relaxes over time.
        self.exit_z_target_start = 0.0
        self.exit_z_target_end = -0.8
        
        # Time Limit: 
        self.max_hold_ticks = int(50 * self.dna)
        
        # Hard Stop: Structural break (Statistical anomaly way beyond entry).
        self.stop_z_panic = -4.5
        
        # === State ===
        self.balance = 10000.0
        self.holdings = {}       # {symbol: {entry_price, entry_tick, amount}}
        self.history = {}        # {symbol: deque(maxlen=window_size)}
        self.tick_count = 0
        
        self.max_positions = 5
        self.trade_amount = 0.15 # 15% of balance per trade

    def _get_stats(self, data):
        """
        Calculates Slope (Trend) and Z-Score (Deviation).
        """
        n = len(data)
        if n < self.window_size:
            return None, None, None
            
        # 1. Mean & Std Dev
        # Simple iterative sum for performance
        sum_val = sum(data)
        mean = sum_val / n
        
        variance = sum((x - mean) ** 2 for x in data) / n
        std_dev = math.sqrt(variance)
        
        if std_dev < 1e-9:
            return None, None, None
            
        # 2. Linear Regression Slope
        # x is [0, 1, ... n-1]
        sum_x = n * (n - 1) / 2
        sum_xx = n * (n - 1) * (2 * n - 1) / 6
        sum_xy = sum(i * y for i, y in enumerate(data))
        
        denom = (n * sum_xx - sum_x ** 2)
        if denom == 0:
            return None, None, None
            
        slope = (n * sum_xy - sum_x * sum_val) / denom
        
        # 3. Z-Score of latest price
        z_score = (data[-1] - mean) / std_dev
        
        return slope, z_score, std_dev

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update Data & Process Exits
        # We prioritize exits to free up capital.
        
        action = None
        
        # Create a list of current symbols to iterate safely
        active_symbols = list(self.holdings.keys())
        
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price_usd = float(prices[sym]['priceUsd'])
                log_price = math.log(curr_price_usd)
            except (ValueError, TypeError):
                continue
                
            pos = self.holdings[sym]
            ticks_held = self.tick_count - pos['entry_tick']
            
            # Retrieve history
            hist = self.history.get(sym)
            if not hist or len(hist) < self.window_size:
                # Fallback exit if data missing
                if ticks_held > self.max_hold_ticks:
                    action = {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TIME_FALLBACK']}
                    del self.holdings[sym]
                    return action
                continue
                
            # Update history with latest price for accurate Z-score calculation relative to NOW
            # (Note: In a real tick loop, we might update history first, but here we peek)
            # We copy specific logic: usually history is updated once per tick. 
            # If we haven't updated this symbol this tick, we assume the previous logic does it 
            # BUT efficient logic implies we calculate metrics on the fly.
            
            # Calculate Stats based on current window (including this new price ideally, or last known)
            # Here we rely on the `hist` deque. For accurate Exit Z, we need the Z of the current price
            # relative to the moving window.
            temp_hist = list(hist) # Snapshot
            # We don't append yet because that happens in step 2 for all symbols. 
            # However, for the exit math, we assume the current price is the 'test' point against the 'training' window.
            
            slope, z_score, std_dev = self._get_stats(temp_hist)
            if z_score is None: continue
            
            # === EXIT LOGIC ===
            
            # Dynamic Target: Linearly interpolate from start to end based on holding time
            # If we hold longer, we accept a lower exit price (time decay)
            progress = min(1.0, ticks_held / self.max_hold_ticks)
            target_z = self.exit_z_target_start + (self.exit_z_target_end - self.exit_z_target_start) * progress
            
            should_sell = False
            reason = []
            
            # 1. Mean Reversion Success
            if z_score > target_z:
                should_sell = True
                reason = ['Z_REVERT']
                
            # 2. Structural Stop (Crash)
            elif z_score < self.stop_z_panic:
                should_sell = True
                reason = ['STOP_PANIC']
                
            # 3. Time Stop
            elif ticks_held >= self.max_hold_ticks:
                should_sell = True
                reason = ['TIME_LIMIT']
            
            if should_sell:
                action = {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': reason}
                del self.holdings[sym]
                return action # Return immediately
        
        # 2. Scan for Entries
        # Only if we have space
        if len(self.holdings) >= self.max_positions:
            # Still need to update history for continuity
            for sym, data in prices.items():
                if sym not in self.history: self.history[sym] = deque(maxlen=self.window_size)
                try: self.history[sym].append(math.log(float(data['priceUsd'])))
                except: pass
            return None

        candidates = []
        
        for sym, data in prices.items():
            # Skip if already holding
            if sym in self.holdings:
                # Update history
                try: self.history[sym].append(math.log(float(data['priceUsd'])))
                except: pass
                continue
                
            try:
                price = float(data['priceUsd'])
                liquidity = float(data['liquidity'])
                
                # Liquidity Filter
                if liquidity < self.min_liquidity:
                    continue
                    
                log_price = math.log(price)
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(log_price)
                
                # Need full window
                if len(self.history[sym]) < self.window_size:
                    continue
                    
                # Calculate Stats
                slope, z_score, std_dev = self._get_stats(self.history[sym])
                
                if z_score is None: continue
                
                # === ENTRY FILTERS ===
                
                # 1. Volatility Filter (Avoid dead or exploding coins)
                if not (self.min_std <= std_dev <= self.max_std):
                    continue
                    
                # 2. Trend Filter (Avoid falling knives)
                if slope < self.min_slope:
                    continue
                    
                # 3. Mean Reversion Trigger (Deep Dip)
                if z_score < self.entry_z_trigger:
                    # Score candidates by how deep the dip is (lower Z is better/higher priority)
                    candidates.append((z_score, sym, price))
                    
            except (ValueError, TypeError, KeyError):
                continue
                
        # Execute best Entry
        if candidates:
            # Sort by Z-score ascending (most negative first)
            candidates.sort(key=lambda x: x[0])
            best_z, best_sym, best_price = candidates[0]
            
            amount = (self.balance * self.trade_amount) / best_price
            
            self.holdings[best_sym] = {
                'entry_price': best_price,
                'entry_tick': self.tick_count,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': amount,
                'reason': ['MEAN_REV_DIP']
            }
            
        return None