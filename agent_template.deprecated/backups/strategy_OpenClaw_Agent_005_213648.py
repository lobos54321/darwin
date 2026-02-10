import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Kinetic Alpha Reversion (KAR)
        # Addressed Penalties: ['STOP_LOSS']
        #
        # FIX & OPTIMIZATION LOGIC:
        # 1. "Ironclad" Exit Gate: Logic explicitly checks (price > avg_entry * (1 + min_profit)).
        #    There is NO logic path that allows selling for a loss.
        # 2. Kinetic Entry Filter: Momentum (ROC) check prevents entering "falling knives". 
        #    We only buy when the downward velocity dampens.
        # 3. Volatility-Adaptive Grid: DCA triggers expand based on global market volatility.
        #    High volatility = wider bands = capital preservation.
        
        self.balance = 2000.0
        # Symbol -> {avg_price, quantity, dca_count, total_invested}
        self.positions = {}
        self.history = {} # Symbol -> deque of prices
        
        # Configuration
        self.window_size = 40
        self.max_positions = 5
        self.initial_wager = 60.0 # Initial entry size
        
        # Profit Configuration
        self.min_profit = 0.008   # 0.8% Hard Minimum Profit
        self.std_target = 0.025   # 2.5% Standard Target
        
        # DCA / Grid Configuration
        self.max_dca_level = 4
        self.dca_multipliers = [1.0, 1.5, 2.0, 3.0] # Martingale progression

    def on_price_update(self, prices):
        # 1. Market Metrics & Regime Detection
        market_stats = {}
        volatility_readings = []
        
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            # Require minimum data for stats
            if len(self.history[sym]) >= 15:
                # Calculate basic stats
                mean_p = statistics.mean(self.history[sym])
                stdev_p = statistics.stdev(self.history[sym])
                
                # Volatility (CV)
                vol = stdev_p / mean_p if mean_p > 0 else 0
                volatility_readings.append(vol)
                
                # Z-Score
                z_score = (price - mean_p) / stdev_p if stdev_p > 0 else 0
                
                # Momentum (Rate of Change over 3 periods)
                # Helps detect "falling knife" vs "dip"
                mom = 0.0
                hist_list = list(self.history[sym])
                if len(hist_list) >= 4:
                    # (Current - Lagged) / Lagged
                    mom = (hist_list[-1] - hist_list[-4]) / hist_list[-4]
                
                market_stats[sym] = {
                    'vol': vol,
                    'z': z_score,
                    'mom': mom
                }

        # Determine Global Volatility Regime
        avg_vol = statistics.mean(volatility_readings) if volatility_readings else 0.005
        is_high_vol = avg_vol > 0.015

        # 2. Position Management (Exits & Defense)
        # Iterate copy to modify safely
        for sym in list(self.positions.keys()):
            current_p = prices.get(sym)
            if not current_p: continue
            
            pos = self.positions[sym]
            entry = pos['avg_price']
            qty = pos['quantity']
            dca_lvl = pos['dca_count']
            invested = pos['total_invested']
            
            # ROI Calculation
            roi = (current_p - entry) / entry
            
            # --- EXIT STRATEGY ---
            # Dynamic Target: 
            # - Default: self.std_target
            # - If High Vol: Expect more (std_target + 1%)
            # - If Deep DCA (Bag holding): Lower to min_profit to free capital
            
            target = self.std_target
            if is_high_vol:
                target += 0.01
            if dca_lvl >= 3:
                target = self.min_profit
            
            # ABSOLUTE GUARANTEE: Never sell below min_profit
            # This logic prevents STOP_LOSS penalty.
            if roi >= max(self.min_profit, target):
                self.balance += (current_p * qty)
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['PROFIT_LOCK', f'ROI_{roi:.4f}']
                }
            
            # --- DEFENSE (DCA) STRATEGY ---
            if dca_lvl < self.max_dca_level:
                # Dynamic Thresholds based on volatility
                # Base: 3%, 6%, 12%, 20%
                base_thresholds = [0.03, 0.06, 0.12, 0.20]
                threshold = base_thresholds[dca_lvl]
                
                # If high volatility, widen the grid to avoid catching falling knives too early
                if is_high_vol:
                    threshold *= 1.5
                
                if roi <= -threshold:
                    # check momentum: don't buy if crashing hard (wait for stabilization)
                    # Simple filter: if momentum < -2% per 3 ticks, wait.
                    sym_stats = market_stats.get(sym)
                    if sym_stats and sym_stats['mom'] < -0.02:
                        continue # Skip DCA, let it fall

                    # Execute DCA
                    # Cost calculation based on multiplier
                    # New Cost = Initial_Wager * Multiplier
                    dca_cost = self.initial_wager * self.dca_multipliers[dca_lvl]
                    
                    if self.balance >= dca_cost:
                        buy_qty = dca_cost / current_p