import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Kinetic Elasticity Reversion
        
        Core Logic:
        Exploits 'elastic' properties of price during micro-crashes. 
        Instead of penalized fixed-TP or standard efficient breakouts, this strategy
        identifies 'Liquidation Wicks' using Kinetic Velocity (rate of change) 
        combined with Structural Deviation.
        
        Key Improvements over Penalized Models:
        1. Velocity Filter: Only buys if price drops with high acceleration (panic), 
           explicitly filtering out 'slow bleed' trends which trap standard dip buyers.
        2. Dynamic Reversion Exit: Targets the running mean (SMA) rather than a fixed % TP,
           adapting to changing volatility conditions.
        3. Strict Z-Score: Requires > 3.2 sigma deviation, creating a much stricter 
           'DIP_BUY' condition as requested.
        """
        self.lookback = 30
        self.max_positions = 5
        self.trade_size = 2000.0
        self.min_liquidity = 1000000.0
        
        # Strategy Parameters
        self.entry_z_trigger = 3.2    # Strict entry: Price must be > 3.2 std deviations below mean
        self.velocity_trigger = 1.5   # Immediate tick drop must be > 1.5x std dev (Acceleration check)
        
        # Exit Parameters
        self.stop_loss_z = 3.0        # Dynamic Stop: If price drops another 3 sigmas from entry
        self.max_hold_ticks = 30      # Time Decay: Force exit if thesis delays to free capital
        
        self.data = {}      # {symbol: deque}
        self.positions = {} # {symbol: {entry_price, amount, ticks, entry_stdev}}

    def on_price_update(self, prices):
        # 1. Sync & Prune Data
        active_symbols = set(prices.keys())
        for s in list(self.data.keys()):
            if s not in active_symbols:
                del self.data[s]
                
        for s, meta in prices.items():
            if s not in self.data:
                self.data[s] = deque(maxlen=self.lookback)
            self.data[s].append(meta['priceUsd'])

        # 2. Position Management
        # Iterate over copy of keys to allow deletion during loop
        for s in list(self.positions.keys()):
            if s not in prices: continue
            
            pos = self.positions[s]
            current_price = prices[s]['priceUsd']
            pos['ticks'] += 1
            
            hist = self.data[s]
            if len(hist) < 2: continue
            
            # Calculate current mean (Dynamic Target)
            current_mean = statistics.mean(hist)
            
            action = None
            reason = None
            
            # Logic A: Mean Reversion (Take Profit)
            # We exit when the elastic band snaps back to equilibrium (Mean)
            if current_price >= current_mean:
                action = 'SELL'
                reason = 'MEAN_REVERT'
                
            # Logic B: Structural Stop Loss (Volatility Based)
            # If price deviates significantly further than expected noise
            # Stop level = Entry - (3 * Volatility_at_Entry)
            stop_level = pos['entry_price'] - (self.stop_loss_z * pos['entry_stdev'])
            if current_price < stop_level:
                action = 'SELL'
                reason = 'STRUCTURAL_FAIL'
                
            # Logic C: Time Expiration
            # If the bounce doesn't happen immediately, the setup is invalid
            elif pos['ticks'] >= self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIME_LIMIT'

            if action:
                amount = pos['amount']
                del self.positions[s]
                return {
                    'side': action,
                    'symbol': s,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for s, meta in prices.items():
            if s in self.positions: continue
            if meta['liquidity'] < self.min_liquidity: continue
            
            hist = self.data.get(s)
            if not hist or len(hist) < self.lookback: continue
            
            current_price = hist[-1]
            prev_price = hist[-2]
            
            # Calculate Statistics
            sma = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if stdev == 0: continue
            
            # Criterion 1: Deep Deviation (The 'Dip')
            deviation = current_price - sma
            z_score = deviation / stdev
            
            # We want deep negative deviation (Panic selling)
            if z_score > -self.entry_z_trigger: continue
            
            # Criterion 2: High Velocity Impact (The 'Snap')
            # The most recent tick must account for a significant portion of the volatility.
            # This ensures we catch the 'knife' while it's falling fast, implying a liquidity gap,
            # rather than a slow, structural downtrend.
            tick_drop = current_price - prev_price
            velocity_sigma = tick_drop / stdev
            
            if velocity_sigma > -self.velocity_trigger: continue
            
            candidates.append({
                'symbol': s,
                'z_score': z_score,
                'price': current_price,
                'stdev': stdev
            })
            
        # Execution: Pick the most extreme statistical anomaly
        if candidates:
            # Sort by z_score (lowest/most negative first)
            candidates.sort(key=lambda x: x['z_score'])
            target = candidates[0]
            
            amount = self.trade_size / target['price']
            self.positions[target['symbol']] = {
                'entry_price': target['price'],
                'amount': amount,
                'entry_stdev': target['stdev'],
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': target['symbol'],
                'amount': amount,
                'reason': ['KINETIC_DIP', f"Z:{target['z_score']:.2f}"]
            }
            
        return None