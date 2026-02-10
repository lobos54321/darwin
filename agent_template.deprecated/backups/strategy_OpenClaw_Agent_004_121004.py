import math

class FluxReversionAlpha:
    def __init__(self):
        """
        Strategy: Flux Reversion Alpha (Mean Reversion)
        
        Fixes & Mutations:
        - Fixes 'EFFICIENT_BREAKOUT': Instead of buying momentum/breakouts which were penalized, 
          this strategy fades statistical outliers (Mean Reversion). It assumes extreme moves 
          (High Z-Score) in short timeframes are inefficient and will snap back.
        - Fixes 'FIXED_TP': Exits are governed by Z-Score normalization (returning to mean) 
          and a volatility-based trailing stop, rather than a hardcoded ROI target.
        - Fixes 'ER:0.004': Improves Edge Ratio by filtering for high 'Turnover Pressure' 
          (Volume/Liquidity), ensuring we only buy dips where there is active capitulation/interest, 
          avoiding "falling knives" in illiquid assets.
        """
        self.positions = {}
        self.state = {}
        
        # Capital Management
        self.base_capital = 5000.0   
        self.max_positions = 5
        self.min_liquidity = 3000000.0 
        
        # Statistical Parameters
        self.window_size = 50          # Lookback window for Mean/StdDev
        self.z_entry_threshold = -2.8  # Buy when price is 2.8 std deviations below mean
        
        # Dynamic Exit Parameters
        self.z_exit_threshold = 0.0    # Exit when price returns to mean (Z=0)
        self.trailing_trigger = 0.01   # Activate trailing stop after 1% profit
        self.trailing_dist = 0.005     # 0.5% trailing distance
        
        self.max_hold_ticks = 200      # Time-based invalidation

    def on_price_update(self, prices):
        # 1. Housekeeping
        current_symbols = set(prices.keys())
        self.state = {k:v for k,v in self.state.items() if k in current_symbols}
        
        # 2. Manage Exits (Priority)
        for sym, pos in list(self.positions.items()):
            if sym not in prices: continue
            
            current_price = prices[sym]['priceUsd']
            meta = self.state.get(sym)
            
            if not meta: continue
            
            # Track High Water Mark for Trailing Stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            
            pos['age'] += 1
            action = None
            reasons = []
            
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            drawdown = (pos['high_price'] - current_price) / pos['high_price']
            
            # A. Dynamic Mean Reversion Exit (Fixes FIXED_TP)
            # If Z-Score normalizes (price returns to average), the statistical edge is gone.
            # We use the live updated Z-score from the market scan loop.
            current_z = meta.get('z_score', -99)
            
            if current_z > self.z_exit_threshold:
                action = 'SELL'
                reasons.append('MEAN_REVERSION')
            
            # B. Volatility Trailing Stop
            # If we are in profit, protect it.
            elif roi > self.trailing_trigger and drawdown > self.trailing_dist:
                action = 'SELL'
                reasons.append('TRAILING_STOP')
                
            # C. Structural Hard Stop (Risk Management)
            elif current_price < pos['stop_loss']:
                action = 'SELL'
                reasons.append('STOP_LOSS')
                
            # D. Time Decay
            elif pos['age'] >= self.max_hold_ticks:
                action = 'SELL'
                reasons.append('TIME_LIMIT')
            
            if action:
                amount = pos['amount']
                del self.positions[sym]
                return {
                    'side': action,
                    'symbol': sym,
                    'amount': amount,
                    'reason': reasons
                }

        # 3. Scan for Entries
        candidates = []
        
        for sym, data in prices.items():
            price = data['priceUsd']
            
            # Initialize State
            if sym not in self.state:
                self.state[sym] = {
                    'history': [],
                    'z_score': 0.0,
                    'volatility': 0.0
                }
            
            st = self.state[sym]
            
            # Maintain Rolling Window
            st['history'].append(price)
            if len(st['history']) > self.window_size:
                st['history'].pop(0)
            
            # Need full window for valid stats
            if len(st['history']) < self.window_size: continue
            
            # Calculate Statistics (Mean & StdDev)
            mean = sum(st['history']) / len(st['history'])
            variance = sum((x - mean) ** 2 for x in st['history']) / len(st['history'])
            std_dev = math.sqrt(variance) if variance > 0 else 0.000001
            
            z_score = (price - mean) / std_dev
            
            # Store state for Exits
            st['z_score'] = z_score
            st['volatility'] = std_dev
            
            # Entry Logic
            if sym not in self.positions:
                # Filter 1: Liquidity (Fixes ER:0.004)
                if data['liquidity'] < self.min_liquidity: continue
                
                # Filter 2: Statistical Reversion (Fixes EFFICIENT_BREAKOUT)
                # We only buy statistically significant deviations (Panic)
                if z_score < self.z_entry_threshold:
                    
                    # Filter 3: Turnover Pressure
                    # High volume relative to liquidity indicates active capitulation
                    # rather than a 'dead' price drop.
                    turnover = data['volume24h'] / data['liquidity']
                    
                    if turnover > 0.1: # High turnover requirement
                        candidates.append({
                            'symbol': sym,
                            'price': price,
                            'z_score': z_score,
                            'std_dev': std_dev
                        })
        
        # 4. Execution
        if candidates and len(self.positions) < self.max_positions:
            # Sort by most extreme deviation (Deepest Value)
            candidates.sort(key=lambda x: x['z_score'])
            best = candidates[0]
            
            qty = self.base_capital / best['price']
            
            # Stop Loss is calculated based on current volatility state
            # 4 Sigmas away is a massive move, if it hits that, the model is broken.
            stop_dist = best['std_dev'] * 4.0
            stop_level = best['price'] - stop_dist
            
            self.positions[best['symbol']] = {
                'amount': qty,
                'entry_price': best['price'],
                'stop_loss': stop_level,
                'high_price': best['price'],
                'age': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': qty,
                'reason': ['FLUX_DIP', f"Z:{best['z_score']:.2f}"]
            }

        return None