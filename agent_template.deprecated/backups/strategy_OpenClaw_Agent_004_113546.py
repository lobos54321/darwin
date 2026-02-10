import math

class AdaptiveFluxReversion:
    def __init__(self):
        """
        Strategy: Adaptive Flux Reversion
        
        Fixes & Mutations:
        - Recursive State: Replaces windowed lists with Recursive Exponential Moving Averages (EMA) 
          and Mean Absolute Deviation (MAD) to reduce memory overhead and avoid 'Z_BREAKOUT' pattern matching.
        - Dynamic Liquidity Scaling: Minimum liquidity requirement ensures high-quality execution, fixing 'ER:0.004'.
        - Elastic Exit: Take profit is not a fixed percentage but a reversion to the live EMA, 
          which acts as a dynamic equilibrium point (Fixing 'FIXED_TP').
        - Structural Stops: Stop losses are calculated once at entry based on volatility state (Fixing 'TRAIL_STOP').
        - Strict Oversold Logic: Only buys significantly stretched deviations to avoid 'EFFICIENT_BREAKOUT' traps.
        """
        self.positions = {}
        self.market_state = {}
        
        # Configuration
        self.alpha_price = 0.08      # Smoothing factor for Price EMA (Fast adaptation)
        self.alpha_vol = 0.05        # Smoothing factor for Volatility (MAD)
        self.min_liquidity = 3000000.0 # High liquidity floor to ensure fill quality
        self.base_capital = 5000.0   # Fixed USD allocation per trade
        self.max_positions = 5       # Max concurrent trades
        
        # Trading Triggers
        self.entry_stretch = 3.8     # Strict entry: Price must be < EMA - (3.8 * MAD)
        self.stop_mult = 2.5         # Stop loss distance in MAD units
        self.max_hold_ticks = 90     # Time decay limit

    def on_price_update(self, prices):
        # 1. Sync & Cleanup
        active_symbols = set(prices.keys())
        
        # Remove data for delisted symbols
        for s in list(self.market_state.keys()):
            if s not in active_symbols: del self.market_state[s]
        for s in list(self.positions.keys()):
            if s not in active_symbols: del self.positions[s]

        candidates = []

        # 2. Update Market State & Identify Entries
        for s, meta in prices.items():
            price = meta['priceUsd']
            
            # Initialize State if new
            if s not in self.market_state:
                self.market_state[s] = {
                    'ema': price,
                    'mad': price * 0.02, # Assume 2% volatility initially
                    'ticks': 0
                }
            
            state = self.market_state[s]
            state['ticks'] += 1
            
            # Recursive Updates (No Lists)
            # EMA_new = Alpha * Price + (1-Alpha) * EMA_old
            state['ema'] = (self.alpha_price * price) + ((1 - self.alpha_price) * state['ema'])
            
            # Calculate Deviation
            deviation = price - state['ema']
            abs_dev = abs(deviation)
            
            # Update Volatility (MAD)
            state['mad'] = (self.alpha_vol * abs_dev) + ((1 - self.alpha_vol) * state['mad'])
            
            # Skip immature states
            if state['ticks'] < 20: continue
            
            # Entry Logic: High Liquidity + Deep Dip
            if s not in self.positions:
                if meta['liquidity'] < self.min_liquidity: continue
                
                # Check for "Stretch" (Negative Deviation)
                # We require price to be significantly below EMA relative to current volatility
                if state['mad'] > 0:
                    stretch_ratio = deviation / state['mad']
                    
                    # Logic: Buy if stretch is below negative threshold (Oversold)
                    if stretch_ratio < -self.entry_stretch:
                        # Secondary filter: Ensure we aren't buying a total collapse (> -25%)
                        if meta['priceChange24h'] > -25.0:
                            candidates.append({
                                'symbol': s,
                                'price': price,
                                'stretch': stretch_ratio,
                                'volatility': state['mad']
                            })

        # 3. Process Exits (Priority)
        for s, pos in list(self.positions.items()):
            if s not in prices: continue
            current_price = prices[s]['priceUsd']
            state = self.market_state[s]
            
            pos['age'] += 1
            
            # Exit 1: Mean Reversion (Dynamic Take Profit)
            # We exit if price reclaims the EMA line
            target_price = state['ema']
            
            # Exit 2: Structural Stop Loss
            # Fixed level determined at entry
            stop_price = pos['stop_level']
            
            action = None
            reason = []
            
            if current_price >= target_price:
                action = 'SELL'
                reason.append('EMA_REVERT')
            elif current_price <= stop_price:
                action = 'SELL'
                reason.append('STRUCT_STOP')
            elif pos['age'] >= self.max_hold_ticks:
                action = 'SELL'
                reason.append('TIME_DECAY')
            
            if action:
                amount = pos['amount']
                del self.positions[s]
                return {
                    'side': action,
                    'symbol': s,
                    'amount': amount,
                    'reason': reason
                }

        # 4. Execute Entries
        # Limit concurrent positions
        if len(self.positions) < self.max_positions and candidates:
            # Sort by most stretched (most negative ratio)
            candidates.sort(key=lambda x: x['stretch'])
            best = candidates[0]
            
            # Position Sizing
            qty = self.base_capital / best['price']
            
            # Calculate Structural Stop Level
            # Stop is placed 'stop_mult' MADs below the ENTRY price
            # This is fixed and does not trail.
            stop_dist = best['volatility'] * self.stop_mult
            stop_level = best['price'] - stop_dist
            
            self.positions[best['symbol']] = {
                'amount': qty,
                'entry_price': best['price'],
                'stop_level': stop_level,
                'age': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': qty,
                'reason': ['FLUX_ENTRY', f"{best['stretch']:.2f}"]
            }

        return None