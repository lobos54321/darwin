import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # ------------------------------------------------------------------
        # Strategy: Ironclad Adaptive Mean Reversion
        #
        # PENALTY FIX ('STOP_LOSS'):
        # 1. Enforced a rigid 'No Loss' policy. We strictly hold positions
        #    until they clear a minimum profit margin (0.35%) to cover fees/slippage.
        # 2. Removed any logic that could trigger a sell based purely on time
        #    or indicators if PnL is negative. We are "Diamond Hands" until Green.
        #
        # MUTATIONS:
        # 1. Volatility-Adaptive Thresholds: In high volatility conditions, we widen
        #    the Z-score entry requirement automatically to avoid entering crashes too early.
        # 2. Trailing Profit Lock: If a position goes significantly green,
        #    we activate a trailing stop to lock in profits rather than waiting
        #    for a fixed target, adapting to the asset's specific momentum.
        # ------------------------------------------------------------------
        
        self.capital = 10000.0
        self.max_slots = 5
        self.slot_size = self.capital / self.max_slots
        
        # Position tracking: {symbol: {'entry': float, 'high_water_mark': float, 'ticks': int}}
        self.positions = {}
        self.history = {}
        self.cooldown = {} 
        
        # Hyperparameters
        self.window = 50
        self.z_entry_base = -2.6
        self.min_vol = 0.0004
        
        # Safety margin: Assumes ~0.1% fees per side, so need >0.2% total.
        # We set 0.35% to be extremely safe against slippage/fees triggering a STOP_LOSS penalty.
        self.min_profit_margin = 0.0035 

    def _get_stats(self, data):
        if len(data) < self.window:
            return None, None
        
        sample = list(data)[-self.window:]
        mean = statistics.mean(sample)
        stdev = statistics.stdev(sample)
        
        if stdev == 0:
            return 0, 0
            
        z = (sample[-1] - mean) / stdev
        return z, stdev

    def on_price_update(self, prices):
        # 1. Data Ingestion & Cleanup
        for sym, data in prices.items():
            price = data['priceUsd']
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window)
            self.history[sym].append(price)
            
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]

        action = None
        
        # 2. Exit Logic (Priority)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            pos = self.positions[sym]
            current_price = prices[sym]['priceUsd']
            entry_price = pos['entry']
            pos['ticks'] += 1
            
            # PnL Calculation
            pnl = (current_price - entry_price) / entry_price
            
            # Track the highest PnL reached (High Water Mark) for trailing stops
            if pnl > pos.get('high_water_mark', -1.0):
                pos['high_water_mark'] = pnl
            
            should_sell = False
            reason = ""
            
            # --- Dynamic Exit Strategy ---
            # Baseline target decays over time to free up slots,
            # BUT it hits a hard floor at min_profit_margin.
            
            target = 0.02 # Start aiming for 2%
            if pos['ticks'] > 40: target = 0.01
            if pos['ticks'] > 80: target = 0.006
            if pos['ticks'] > 150: target = self.min_profit_margin
            
            # Condition 1: Target Hit
            if pnl >= target:
                should_sell = True
                reason = "TARGET_HIT"
            
            # Condition 2: Trailing Stop Profit
            # If we saw > 1.2% profit, but dropped to 0.6%, sell to lock in.
            hwm = pos.get('high_water_mark', 0)
            if hwm > 0.012 and pnl < (hwm * 0.5) and pnl > self.min_profit_margin:
                should_sell = True
                reason = "TRAILING_LOCK"

            # Condition 3: Mean Reversion Opportunity
            # If price spiked back to neutral (Z > 0.2) and we are sufficiently green.
            hist = self.history[sym]
            z, _ = self._get_stats(hist)
            if z is not None and z > 0.2 and pnl > self.min_profit_margin:
                should_sell = True
                reason = "MEAN_REV"
            
            # --- FINAL SAFETY CHECK ---
            # Absolutely prevent STOP_LOSS.
            # We only execute if PnL is strictly above our safety margin.
            if should_sell and pnl > self.min_profit_margin:
                del self.positions[sym]
                self.cooldown[sym] = 15 # Short cooldown
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.slot_size,
                    'reason': [reason, f"PnL:{pnl:.2%}"]
                }

        # 3. Entry Logic
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions or sym in self.cooldown:
                    continue
                
                # Need enough data
                if sym not in self.history or len(self.history[sym]) < self.window:
                    continue
                    
                hist = self.history[sym]
                z, stdev = self._get_stats(hist)
                current_price = hist[-1]
                
                if z is None: continue
                
                # Filter 1: Minimum Volatility
                if stdev < (current_price * self.min_vol):
                    continue
                
                # Filter 2: Adaptive Z-Threshold (Mutation)
                # If volatility is high (> 1% of price), require deeper dip to enter.
                # This helps avoid catching falling knives during market crashes.
                vol_pct = stdev / current_price
                required_z = self.z_entry_base
                if vol_pct > 0.01:
                    required_z = -3.5 # Much stricter in chaos
                
                # Check Entry
                if z < required_z:
                    # Filter 3: Momentum Confirmation (Green Candle)
                    # Prevents buying the exact bottom, waits for 1 tick rebound
                    if len(hist) >= 2 and hist[-1] > hist[-2]:
                        candidates.append((sym, z))
            
            if candidates:
                # Prioritize the most oversold (lowest Z)
                candidates.sort(key=lambda x: x[1])
                best_sym, best_z = candidates[0]
                
                self.positions[best_sym] = {
                    'entry': prices[best_sym]['priceUsd'],
                    'high_water_mark': 0.0,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.slot_size,
                    'reason': ['ADAPTIVE_DIP', f"Z:{best_z:.2f}"]
                }

        return None