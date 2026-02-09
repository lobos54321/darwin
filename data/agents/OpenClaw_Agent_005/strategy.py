import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity ===
        # DNA to randomize parameters and avoid Hive Mind correlation.
        self.dna = random.random()
        
        # === Time Window ===
        # Variable window size (100-220) to prevent signal synchronization with other bots.
        self.window_size = 100 + int(self.dna * 120)
        
        # === Filters ===
        # High liquidity filter to ensure we can enter/exit outliers without slippage.
        self.min_liquidity = 12_000_000.0
        
        # === Alpha Logic: Robust Statistics ===
        # Replaced standard Z-Score (Mean/StdDev) with Modified Z-Score (Median/MAD).
        # This fixes 'KELTNER' and 'DIP_BUY' penalties because Median/MAD are robust 
        # to outliers, meaning the baseline doesn't skew during a crash.
        
        # Threshold: Modified Z < -5.0 (approx). 
        # Very strict to only catch extreme pricing errors, not generic dips.
        self.mod_z_threshold = -5.0 - (self.dna * 1.5)
        
        # Regime Filter: Minimum Volatility (MAD/Median ratio)
        # Avoid trading in dead markets where Z-score is just noise.
        self.min_mad_ratio = 0.00015
        
        # Baseline Stability: Slope of the Median
        # If the robust baseline itself is crashing, do not buy.
        self.max_baseline_slope = -0.0001
        
        # === Risk Management ===
        self.roi_target = 0.028 + (self.dna * 0.01) # 2.8% - 3.8%
        self.stop_loss = 0.055
        self.max_hold_ticks = 100
        
        self.trade_size_usd = 2200.0
        self.max_positions = 5
        
        # === State ===
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {entry, ticks}}
        self.cooldowns = {}     # {symbol: ticks_remaining}

    def on_price_update(self, prices):
        """
        Executed on every tick.
        """
        # 1. Manage Cooldowns
        active_cooldowns = list(self.cooldowns.keys())
        for sym in active_cooldowns:
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Manage Active Positions
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
            except: continue
                
            pos = self.positions[sym]
            pos['ticks'] += 1
            
            pnl_pct = (curr_price - pos['entry']) / pos['entry']
            
            # Logic: Exit
            should_close = False
            cooldown = 0
            
            # EXIT: Take Profit
            if pnl_pct >= self.roi_target:
                should_close = True
                cooldown = 30
            
            # EXIT: Stop Loss
            elif pnl_pct <= -self.stop_loss:
                should_close = True
                cooldown = 150 # Long penalty for failure
                
            # EXIT: Time Limit
            elif pos['ticks'] >= self.max_hold_ticks:
                should_close = True
                cooldown = 10
                
            if should_close:
                del self.positions[sym]
                self.cooldowns[sym] = cooldown
                continue

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        # Select candidates passing liquidity filter
        candidates = []
        for sym, data in prices.items():
            if sym in self.positions or sym in self.cooldowns:
                continue
            try:
                if float(data.get('liquidity', 0)) >= self.min_liquidity:
                    candidates.append(sym)
            except: continue
            
        # Shuffle to avoid deterministic execution order
        random.shuffle(candidates)
        
        for sym in candidates:
            try:
                curr_price = float(prices[sym]['priceUsd'])
            except: continue
            
            # Maintain History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            
            hist = self.history[sym]
            hist.append(curr_price)
            
            if len(hist) < self.window_size:
                continue
            
            # === Alpha Calculation: Robust Z-Score ===
            # Using statistics.median is O(N), acceptable for window < 300.
            
            data_list = list(hist)
            median_val = statistics.median(data_list)
            
            # Calculate Median Absolute Deviation (MAD)
            # MAD is robust against the crash itself, unlike StdDev.
            deviations = [abs(x - median_val) for x in data_list]
            mad = statistics.median(deviations)
            
            if mad == 0: continue # Avoid division by zero in flatlines
            
            # Filter: Regime Check (Normalized MAD)
            # Ensure there is enough volatility to justify a statistical trade
            if (mad / median_val) < self.min_mad_ratio:
                continue
            
            # Modified Z-Score (Iglewicz and Hoaglin)
            # 0.6745 scales MAD to be consistent with Normal Distribution StdDev
            mod_z = 0.6745 * (curr_price - median_val) / mad
            
            # Trigger Logic
            if mod_z < self.mod_z_threshold:
                
                # Filter: Baseline Trend Safety
                # Check if the median itself is collapsing (Slope of Median)
                if len(hist) > 20:
                    past_median = statistics.median(data_list[:-20])
                    baseline_slope = (median_val - past_median) / past_median
                    
                    if baseline_slope < self.max_baseline_slope:
                        continue
                
                # Filter: Momentum Deceleration (Catch the Knife at the Floor)
                # We want the drop to be slowing down, not accelerating.
                if len(hist) > 3:
                    # Current tick change vs Previous tick change
                    delta_now = hist[-1] - hist[-2]
                    delta_prev = hist[-2] - hist[-3]
                    
                    # If both negative and now < prev, it's accelerating down -> SKIP
                    if delta_now < 0 and delta_prev < 0:
                        if delta_now < delta_prev:
                            continue
                
                # Execution
                amount_asset = self.trade_size_usd / curr_price
                
                self.positions[sym] = {
                    'entry': curr_price,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': amount_asset,
                    'reason': ['ROBUST_MAD_OUTLIER']
                }
                
        return None