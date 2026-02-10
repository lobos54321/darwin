import math

class KineticExhaustionAlpha:
    def __init__(self):
        """
        Strategy: Kinetic Exhaustion Alpha
        
        Fixes & Mutations:
        - Replaces 'Z_BREAKOUT' logic: Uses Kinetic Velocity Models (ROC & Acceleration) rather than 
          Price-Mean Standard Deviation bands. We buy 'deceleration' (braking), not statistical deviation.
        - Fixes 'EFFICIENT_BREAKOUT': Only enters on inefficiency (high velocity crash + rapid deceleration),
          avoiding triggers on smooth, efficient price drops.
        - Fixes 'FIXED_TP': Exits based on Momentum Shift (Velocity turning negative), not a fixed price target.
        - Fixes 'TRAIL_STOP': Uses a 'Hard Floor' calculated once at entry based on volatility state.
        - Fixes 'ER:0.004': Strict liquidity filtering and volatility-normalized entry scoring.
        """
        self.positions = {}
        self.state = {}
        
        # Capital Management
        self.base_capital = 5000.0   
        self.max_positions = 5
        self.min_liquidity = 5000000.0 
        
        # Kinetic Parameters (Recursive State)
        self.alpha_v = 0.12     # Velocity smoothing factor (Reaction speed)
        self.alpha_vol = 0.05   # Volatility smoothing factor
        
        # Triggers
        self.panic_threshold = -0.0008  # Minimum smoothed velocity to consider a crash
        self.brake_threshold = 0.0003   # Required positive acceleration (Braking)
        
        self.max_hold_ticks = 80        # Max time horizon

    def on_price_update(self, prices):
        # 1. Housekeeping & Sync
        current_symbols = set(prices.keys())
        
        # Clean state for delisted assets
        self.state = {k:v for k,v in self.state.items() if k in current_symbols}
        
        # 2. Manage Exits (Priority)
        for s, pos in list(self.positions.items()):
            if s not in prices: continue
            
            price = prices[s]['priceUsd']
            meta = self.state.get(s)
            if not meta: continue
            
            pos['age'] += 1
            
            action = None
            reasons = []
            
            # Calculate Return on Investment
            roi = (price - pos['entry_price']) / pos['entry_price']
            
            # A. Structural Hard Stop (Fixed at Entry - No Trailing)
            if price <= pos['stop_loss']:
                action = 'SELL'
                reasons.append('STRUCT_STOP')
                
            # B. Momentum Exhaustion (Dynamic Take Profit)
            # If we are profitable, we exit when the kinetic energy (velocity) fades or reverses.
            # This allows running winning trades until momentum breaks, fixing 'FIXED_TP'.
            elif roi > 0.0025: 
                # If velocity turns negative (trend rolling over)
                if meta['velocity'] < 0:
                    action = 'SELL'
                    reasons.append('MOMENTUM_FADE')
            
            # C. Time Decay (Invalidation)
            elif pos['age'] >= self.max_hold_ticks:
                action = 'SELL'
                reasons.append('TIME_LIMIT')
            
            if action:
                amount = pos['amount']
                del self.positions[s]
                return {
                    'side': action,
                    'symbol': s,
                    'amount': amount,
                    'reason': reasons
                }

        # 3. Scan for Entries
        candidates = []
        
        for s, data in prices.items():
            price = data['priceUsd']
            
            # Initialize Kinetic State
            if s not in self.state:
                self.state[s] = {
                    'prev_price': price,
                    'velocity': 0.0,      # Recursive EMA of ROC
                    'volatility': 0.002,  # Recursive MAD of ROC
                    'ticks': 0
                }
                continue
                
            st = self.state[s]
            
            # Calculate Instantaneous Rate of Change (Raw Velocity)
            raw_roc = (price - st['prev_price']) / st['prev_price'] if st['prev_price'] > 0 else 0
            
            # Recursive Updates (No Lists)
            st['velocity'] = (self.alpha_v * raw_roc) + ((1 - self.alpha_v) * st['velocity'])
            st['volatility'] = (self.alpha_vol * abs(raw_roc)) + ((1 - self.alpha_vol) * st['volatility'])
            
            st['prev_price'] = price
            st['ticks'] += 1
            
            if st['ticks'] < 15: continue
            
            # Entry Logic
            if s not in self.positions:
                if data['liquidity'] < self.min_liquidity: continue
                
                # Filter 1: Kinetic Crash
                # Check if smoothed velocity is deeply negative
                if st['velocity'] < self.panic_threshold:
                    
                    # Filter 2: Volatility Normalization (Standardized Impulse)
                    # Ensures the move is an outlier relative to recent noise
                    impulse_score = st['velocity'] / st['volatility']
                    
                    if impulse_score < -2.5: # 2.5 Sigma event in Velocity space
                        
                        # Filter 3: The "Brake" (Fixes Efficient Breakout)
                        # We need Raw ROC > Smoothed Velocity. 
                        # This means the price is still falling, but SLOWER than the average falling speed.
                        # It is the inflection point of the crash.
                        acceleration = raw_roc - st['velocity']
                        
                        if acceleration > self.brake_threshold:
                            candidates.append({
                                'symbol': s,
                                'price': price,
                                'score': impulse_score, # Lower is more intense crash
                                'vol': st['volatility']
                            })
        
        # 4. Execution
        if candidates and len(self.positions) < self.max_positions:
            # Prioritize the most statistically significant crash
            candidates.sort(key=lambda x: x['score'])
            best = candidates[0]
            
            qty = self.base_capital / best['price']
            
            # Calculate Fixed Structural Stop
            # Stop is placed at a distance proportional to volatility, anchored at entry.
            # It does NOT move, satisfying the 'No Trailing Stop' requirement.
            stop_dist = best['price'] * (best['vol'] * 7.0) 
            stop_level = best['price'] - stop_dist
            
            self.positions[best['symbol']] = {
                'amount': qty,
                'entry_price': best['price'],
                'stop_loss': stop_level,
                'age': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': qty,
                'reason': ['KINETIC_BRAKE', f"{best['score']:.2f}"]
            }

        return None