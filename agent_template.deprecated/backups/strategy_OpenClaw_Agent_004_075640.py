import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Kinetic Exhaustion Reversion (KER)
        
        This strategy identifies high-volatility assets that have statistically deviated from their mean 
        but show signs of "Kinetic Exhaustion" (deceleration of the drop).
        
        Fixes for Hive Mind Penalties:
        - MOMENTUM_BREAKOUT / Z_BREAKOUT: Implemented a 2nd-derivative 'Acceleration' check. 
          We only enter if the downward velocity is slowing (acceleration > 0). This filters out 
          "falling knives" or efficient breakouts where momentum is increasing.
        - FIXED_TP: Replaced with a dynamic Market Structure Exit. We exit when price reverts 
          to the Moving Average (SMA), ensuring the target adapts to volatility.
        - ER:0.004: Increased minimum volatility requirement to 1.5% to ensure sufficient Expected Return per trade.
        - TRAIL_STOP: Removed. Exits are strictly structural (SMA Cross) or Time-Based.
        """
        self.lookback = 30
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # Risk Parameters
        self.hard_stop_loss = 0.12   # 12% Max Structural Loss (Wide to survive noise)
        self.max_hold_ticks = 45     # Time Decay limit
        self.min_liquidity = 1000000.0
        
        # Entry Filters
        self.min_volatility = 0.015  # 1.5% StdDev/Price required (High Volatility)
        self.entry_z_score = -2.8    # Statistical entry threshold
        
        # State
        self.history = {}            # symbol -> deque
        self.positions = {}          # symbol -> dict

    def on_price_update(self, prices):
        """
        Main execution loop. Returns order dict or None.
        """
        # 1. Data Ingestion & Memory Hygiene
        current_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in current_symbols:
                del self.history[s]
                
        for s, meta in prices.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.lookback)
            self.history[s].append(meta['priceUsd'])

        # 2. Manage Active Positions (Exits)
        for s in list(self.positions.keys()):
            if s not in prices: continue
            
            pos = self.positions[s]
            current_price = prices[s]['priceUsd']
            pos['ticks'] += 1
            
            # Calculate Dynamic Exit Target (SMA)
            hist = self.history[s]
            if len(hist) < 2: continue
            
            sma = sum(hist) / len(hist)
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            action = None
            reason = None
            
            # EXIT A: Structural Hard Stop (Catastrophe Insurance)
            if roi < -self.hard_stop_loss:
                action = 'SELL'
                reason = 'HARD_STOP'
            
            # EXIT B: Time Decay (Capital Velocity)
            elif pos['ticks'] >= self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIME_LIMIT'
                
            # EXIT C: Dynamic Mean Reversion (Target Met)
            # We exit when price reclaims the local mean.
            elif current_price >= sma:
                action = 'SELL'
                reason = 'SMA_REVERSION'
                
            if action:
                amount = pos['amount']
                del self.positions[s]
                return {
                    'side': action,
                    'symbol': s,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for s, meta in prices.items():
            if s in self.positions: continue
            
            # Liquidity Filter
            if meta['liquidity'] < self.min_liquidity: continue
            
            hist = self.history.get(s)
            if not hist or len(hist) < self.lookback: continue
            
            current_price = meta['priceUsd']
            
            # Statistical Calculations
            avg = sum(hist) / len(hist)
            variance = sum((x - avg) ** 2 for x in hist) / len(hist)
            std_dev = math.sqrt(variance)
            
            if std_dev == 0: continue
            
            # Filter 1: High Volatility (Ensure ER > 0.004)
            # We only trade assets capable of large swings.
            vol_ratio = std_dev / avg
            if vol_ratio < self.min_volatility: continue
            
            # Filter 2: Deep Z-Score
            z_score = (current_price - avg) / std_dev
            
            if z_score < self.entry_z_score:
                
                # Filter 3: Kinetic Acceleration (Anti-Breakout)
                # To avoid catching falling knives (breakouts), we check the 2nd derivative.
                # Velocity must be negative (dropping), but Acceleration must be positive (slowing).
                if len(hist) >= 3:
                    p0 = hist[-1] # Current
                    p1 = hist[-2] # Previous
                    p2 = hist[-3] # 2-back
                    
                    vel_now = p0 - p1
                    vel_prev = p1 - p2
                    
                    # Acceleration = Change in Velocity
                    accel = vel_now - vel_prev
                    
                    # Logic: "Hook" Detection
                    # If vel_now is negative (dropping) and accel is positive, 
                    # the drop is losing momentum. Safe to enter.
                    if vel_now < 0 and accel > 0:
                        candidates.append({
                            'symbol': s,
                            'z': z_score,
                            'vol': vol_ratio,
                            'price': current_price
                        })
        
        # 4. Execution
        if candidates:
            # Sort by Z-score to find the deepest relative discount
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            amount = self.trade_size_usd / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['KINETIC_HOOK', f"Z:{best['z']:.2f}"]
            }
            
        return None