import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Volatility Mean Reversion (AVMR)
        
        Mutations to fix penalties:
        1. EFFICIENT_BREAKOUT: Implemented a 'Volatility Expansion Brake'. 
           We calculate the rate of change of the Standard Deviation. 
           If Volatility is expanding rapidly (Expansion Ratio > 1.05), we assume a breakout 
           event and inhibit fading, preventing 'catching a falling knife'.
           
        2. ER:0.004 (Low Edge): 
           - Increased Liquidity requirement to reduce slippage impact.
           - Added Z-Score Velocity check: We only enter if the downward momentum is decelerating 
             (Z-score isn't plunging faster than the previous tick).
             
        3. FIXED_TP: 
           - Removed fixed Z-target. 
           - Implemented a Volatility-Adjusted Trailing Stop. 
           - The profit target floats based on the asset's realized volatility (ATR-like proxy), 
             allowing winners to run during high-volatility mean reversion events.
        """
        # Configuration
        self.window_size = 30           # Shorter window for faster reaction
        self.min_liquidity = 5000000.0  # Only trade high-liquid assets
        self.max_positions = 3          # Focus on best setups
        self.position_size_usd = 500.0  # Larger size per trade given fewer positions
        
        # Entry Filters
        self.entry_z = -2.5             # Entry trigger
        self.entry_rsi = 28             # Oversold trigger
        self.max_expansion = 1.05       # Volatility expansion limit (Breakout filter)
        self.z_velocity_limit = -0.5    # Max allowed drop in Z-score per tick
        
        # Dynamic Exit Logic
        self.stop_loss_pct = 0.04       # 4% Hard stop
        self.max_hold_ticks = 45        # Time decay
        self.trailing_start_z = 0.0     # Start trailing once price recovers to mean
        
        # State
        self.history = {}               # {symbol: deque(maxlen=window)}
        self.vol_history = {}           # {symbol: deque(maxlen=5)} - Track stdev changes
        self.positions = {}             # {symbol: {data}}
        self.tick_count = 0

    def get_indicators(self, symbol, current_price):
        """Calculates Z-score, RSI, and Volatility Expansion."""
        prices = self.history[symbol]
        
        if len(prices) < self.window_size:
            return None

        # 1. Basic Stats
        try:
            mean = statistics.mean(prices)
            stdev = statistics.stdev(prices)
        except statistics.StatisticsError:
            return None

        if stdev == 0:
            return None

        z_score = (current_price - mean) / stdev
        
        # 2. RSI Calculation
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        if len(deltas) == 0:
            rsi = 50
        elif not losses:
            rsi = 100
        elif not gains:
            rsi = 0
        else:
            avg_gain = sum(gains) / len(deltas) # Simple average for speed/stability
            avg_loss = sum(losses) / len(deltas)
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        # 3. Volatility Expansion (Breakout Detection)
        # Compare current stdev to recent average stdev to detect explosions
        vol_hist = self.vol_history.get(symbol, deque(maxlen=5))
        if len(vol_hist) > 0:
            avg_prev_vol = sum(vol_hist) / len(vol_hist)
            expansion_ratio = stdev / avg_prev_vol if avg_prev_vol > 0 else 1.0
        else:
            expansion_ratio = 1.0
            
        # Update Vol History
        if symbol not in self.vol_history:
            self.vol_history[symbol] = deque(maxlen=5)
        self.vol_history[symbol].append(stdev)

        return {
            'z': z_score,
            'rsi': rsi,
            'expansion': expansion_ratio,
            'stdev': stdev
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # Identify active symbols
        active_symbols = set(prices.keys())
        
        # 1. Manage Exits first (sell before buy to free slots)
        action = None
        
        # Create list to modify dict during iteration
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_data = prices.get(symbol)
            
            if not current_data:
                continue
                
            curr_price = current_data['priceUsd']
            entry_price = pos['entry_price']
            highest_price = pos['highest_price']
            
            # Update High Water Mark
            if curr_price > highest_price:
                self.positions[symbol]['highest_price'] = curr_price
                highest_price = curr_price
            
            # ROI Calc
            roi = (curr_price - entry_price) / entry_price
            
            # Get fresh stats for exit logic
            stats = self.get_indicators(symbol, curr_price)
            z_score = stats['z'] if stats else 0
            
            should_exit = False
            reason = ''
            
            # A. Hard Stop Loss
            if roi < -self.stop_loss_pct:
                should_exit = True
                reason = 'STOP_LOSS'
            
            # B. Time Decay
            elif self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                should_exit = True
                reason = 'TIMEOUT'
            
            # C. Trailing Stop (Dynamic)
            # If we crossed the mean (Z > 0), activate tight trail
            elif z_score > 0:
                # Calculate dynamic trail distance based on volatility (0.5 * stdev)
                # Approximation: stdev/price roughly gives volatility %
                vol_pct = (stats['stdev'] / curr_price) if stats else 0.01
                trail_dist = max(0.005, vol_pct * 0.5) 
                
                if curr_price < highest_price * (1 - trail_dist):
                    should_exit = True
                    reason = 'TRAILING_PROFIT'
            
            if should_exit:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0, # Indicates close full position usually, or handled by caller
                    'reason': [reason]
                }

        # 2. Manage Entries
        # Sort candidates by liquidity to prioritize stability
        candidates = []
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
            
            # Basic filters
            if data['liquidity'] < self.min_liquidity:
                continue
                
            # History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(data['priceUsd'])
            
            if len(self.history[symbol]) < self.window_size:
                continue
                
            candidates.append((symbol, data))

        # Check signals if we have space
        if len(self.positions) < self.max_positions:
            for symbol, data in candidates:
                curr_price = data['priceUsd']
                stats = self.get_indicators(symbol, curr_price)
                
                if not stats:
                    continue
                
                z = stats['z']
                rsi = stats['rsi']
                exp = stats['expansion']
                
                # PRE-ENTRY CONDITIONS
                
                # 1. Deep Value: Z-score is low
                if z < self.entry_z:
                    
                    # 2. Oversold RSI check
                    if rsi < self.entry_rsi:
                        
                        # 3. Volatility Brake (Anti-EFFICIENT_BREAKOUT)
                        # If volatility is expanding too fast, it's a breakout, not a dip.
                        if exp < self.max_expansion:
                            
                            # 4. Z-Velocity Check (Anti-Falling Knife)
                            # Check previous Z score to ensure we aren't accelerating down
                            # We need history of Z scores, or reconstruct previous briefly
                            prev_prices = list(self.history[symbol])[:-1]
                            if len(prev_prices) > 2:
                                try:
                                    p_mean = statistics.mean(prev_prices)
                                    p_stdev = statistics.stdev(prev_prices)
                                    if p_stdev > 0:
                                        prev_z = (prev_prices[-1] - p_mean) / p_stdev
                                        z_velocity = z - prev_z
                                        
                                        # If velocity is very negative, price is crashing hard. Wait.
                                        if z_velocity > self.z_velocity_limit:
                                            # Register Trade
                                            self.positions[symbol] = {
                                                'entry_price': curr_price,
                                                'highest_price': curr_price,
                                                'entry_tick': self.tick_count
                                            }
                                            return {
                                                'side': 'BUY',
                                                'symbol': symbol,
                                                'amount': self.position_size_usd,
                                                'reason': ['VOL_ADAPTIVE_REV']
                                            }
                                except:
                                    pass # Skip if calc fails

        return None