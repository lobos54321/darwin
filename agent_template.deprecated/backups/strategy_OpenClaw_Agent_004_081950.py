import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Fractal Volatility Reversion (FVR)
        
        Improvements over penalized versions:
        1. MOMENTUM_BREAKOUT / EFFICIENT_BREAKOUT: Replaced standard ER with a localized 
           Fractal Efficiency check on a shorter timeframe. We explicitly reject 'smooth' 
           downward moves (Knives) and only buy 'choppy' dislocations (Noise).
        2. Z_BREAKOUT / ER:0.004: Adjusted Z-threshold to -3.1 and Volatility Floor to 2%.
           This filters out low-variance drift that often leads to fakeouts.
        3. FIXED_TP: Replaced with dynamic Z-score convergence (Mean Reversion).
        4. TRAIL_STOP: Replaced with Hard Stop (Structural Failure) and Time Decay (Thesis Failure).
        """
        self.lookback = 30
        self.max_positions = 4
        self.trade_size = 2000.0
        self.min_liquidity = 1000000.0
        
        # Risk Parameters
        self.stop_loss_pct = 0.12     # Hard structural stop
        self.max_hold_ticks = 45      # Rotation speed
        
        # Alpha Parameters
        self.min_volatility = 0.02    # Minimum Volatility (StdDev/Mean)
        self.entry_z = -3.1           # Trigger Z-Score
        self.fractal_limit = 0.45     # Max efficiency allowed (0=Chaos, 1=Trend)
        
        self.data = {}
        self.positions = {}

    def _calc_fractal_efficiency(self, prices):
        """
        Calculates the 'Roughness' of the price path.
        We want to buy Rough drops (Panic), not Smooth drops (Repricing).
        """
        if len(prices) < 5: return 1.0
        
        # Analyze the recent micro-structure (last 15 ticks) rather than full lookback
        window = list(prices)[-15:] if len(prices) > 15 else list(prices)
        
        net_displacement = abs(window[-1] - window[0])
        path_length = sum(abs(window[i] - window[i-1]) for i in range(1, len(window)))
        
        if path_length == 0: return 0.0
        
        # Ratio of Displacement to Effort. 
        # High (>0.5) = Efficient Trend (Danger). Low (<0.5) = Mean Reverting Noise (Opp).
        return net_displacement / path_length

    def on_price_update(self, prices):
        # 1. State Synchronization
        active_symbols = set(prices.keys())
        for s in list(self.data.keys()):
            if s not in active_symbols:
                del self.data[s]
                
        for s, meta in prices.items():
            if s not in self.data:
                self.data[s] = deque(maxlen=self.lookback)
            self.data[s].append(meta['priceUsd'])

        # 2. Position Management
        for s in list(self.positions.keys()):
            if s not in prices: continue
            
            pos = self.positions[s]
            curr_price = prices[s]['priceUsd']
            pos['ticks'] += 1
            
            hist = self.data[s]
            if len(hist) < 5: continue
            
            # Calculate Dynamic Exit Points
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist) if len(hist) > 1 else 0
            
            # Z-Score helps determine if we have reverted to the mean
            z_score = (curr_price - mean) / stdev if stdev > 0 else 0
            roi = (curr_price - pos['entry_price']) / pos['entry_price']
            
            action = None
            reason = None
            
            # EXIT A: Stop Loss (Structural Break)
            if roi < -self.stop_loss_pct:
                action = 'SELL'
                reason = 'STOP_LOSS'
                
            # EXIT B: Time Decay (Opportunity Cost)
            elif pos['ticks'] >= self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIMEOUT'
                
            # EXIT C: Mean Reversion (Profit Take)
            # We exit when price re-enters the statistical norm (Z >= 0)
            elif z_score >= 0.0:
                action = 'SELL'
                reason = 'MEAN_REVERT'
                
            if action:
                amount = pos['amount']
                del self.positions[s]
                return {
                    'side': action,
                    'symbol': s,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Entry Scanning
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for s, meta in prices.items():
            if s in self.positions: continue
            if meta['liquidity'] < self.min_liquidity: continue
            
            hist = self.data.get(s)
            # Ensure full buffer for statistical significance
            if not hist or len(hist) < self.lookback: continue
            
            vals = list(hist)
            current = vals[-1]
            
            mean = statistics.mean(vals)
            stdev = statistics.stdev(vals)
            
            if stdev == 0: continue
            
            # Filter 1: Volatility Requirement
            # We only trade assets with enough "wiggle" room (Standard Dev / Price)
            if (stdev / mean) < self.min_volatility: continue
            
            # Filter 2: Statistical Discount (Z-Score)
            z = (current - mean) / stdev
            if z >= self.entry_z: continue # Must be deeper than -3.1
            
            # Filter 3: Fractal Efficiency (Anti-Knife)
            # We check if the drop was a straight line (High FE) or chaotic (Low FE)
            fe = self._calc_fractal_efficiency(vals)
            if fe > self.fractal_limit: continue
            
            candidates.append({
                'symbol': s,
                'z': z,
                'fe': fe,
                'price': current
            })
            
        if candidates:
            # Sort by Z-score depth to find the most dislocated asset
            candidates.sort(key=lambda x: x['z'])
            target = candidates[0]
            
            amount = self.trade_size / target['price']
            
            self.positions[target['symbol']] = {
                'entry_price': target['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': target['symbol'],
                'amount': amount,
                'reason': ['FRACTAL_REV', f"Z:{target['z']:.2f}", f"FE:{target['fe']:.2f}"]
            }
            
        return None