import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Configuration ---
        self.window_size = 40
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Filters ---
        # Stricter liquidity to ensure statistical relevance
        self.min_liquidity = 15_000_000.0
        self.min_volume_24h = 2_000_000.0
        
        # --- Strategy Parameters (Penalty Fixes) ---
        # Fix for 'DIP_BUY':
        # Instead of buying raw drops, we filter by Relative Volatility.
        # We only buy dips in stable regimes (Low Volatility).
        # We assume High Volatility dips are "Falling Knives".
        self.max_relative_volatility = 0.006  # Max StdDev/Mean allowed (0.6%)
        
        # Fix for 'KELTNER' / 'OVERSOLD':
        # Use deep Z-score statistical bounds rather than ATR channels or RSI.
        self.z_entry_threshold = -2.85   # Deep deviation required
        self.z_crash_guard = -5.0        # Avoid extreme outliers (Flash crashes)
        
        # Fix for Momentum:
        # Green Tick Confirmation: Current price must be >= Previous Price
        # to ensure the immediate selling pressure has paused.
        
        # --- Exit Params ---
        self.take_profit = 0.022         # 2.2% Target
        self.stop_loss = -0.015          # 1.5% Hard Stop
        self.trailing_activation = 0.01  # Activate trailing stop after 1% gain
        self.max_hold_ticks = 60         # Time limit
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Clean up history for removed symbols
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]

        # 2. Manage Existing Positions
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            
            roi = (current_price - entry_price) / entry_price
            
            exit_reason = None
            
            # Dynamic Trailing Stop
            # If ROI > 1%, raise stop loss to break-even (+0.2% fee cover)
            effective_stop = self.stop_loss
            if roi > self.trailing_activation:
                effective_stop = 0.002 
            
            if roi >= self.take_profit:
                exit_reason = 'TAKE_PROFIT'
            elif roi <= effective_stop:
                exit_reason = 'STOP_LOSS'
            elif self.tick_count - pos['entry_tick'] >= self.max_hold_ticks:
                exit_reason = 'TIMEOUT'
                
            if exit_reason:
                amount = pos['amount']
                del self.positions[symbol]
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': amount, 
                    'reason': [exit_reason]
                }

        # 3. Check for New Entries
        if len(self.positions) >= self.max_positions:
            return None

        # Select Candidates based on Liquidity
        candidates = []
        for s, data in prices.items():
            if data['priceUsd'] <= 0: continue
            if data['liquidity'] >= self.min_liquidity and data.get('volume24h', 0) >= self.min_volume_24h:
                candidates.append(s)
        
        # Sort by liquidity descending (Trade the most stable assets first)
        candidates.sort(key=lambda s: prices[s]['liquidity'], reverse=True)
        
        for symbol in candidates:
            # Skip if already in position
            if symbol in self.positions:
                continue
                
            price = prices[symbol]['priceUsd']
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            # Need full window for stats
            if len(self.history[symbol]) < self.window_size:
                continue

            # --- Statistical Calculations ---
            history_list = list(self.history[symbol])
            
            # Calculate Mean
            mean_price = sum(history_list) / len(history_list)
            
            # Calculate Variance & StdDev
            variance = sum((x - mean_price) ** 2 for x in history_list) / len(history_list)
            std_dev = math.sqrt(variance)
            
            if std_dev == 0: continue
            
            # Calculate Z-Score (Number of std devs from mean)
            z_score = (price - mean_price) / std_dev
            
            # --- Primary Filters (Mutation: Volatility Clamping) ---
            
            # 1. Relative Volatility Filter
            # If the asset is moving too violently relative to its price, ignore it.
            # This avoids "Catching a falling knife" during market crashes.
            relative_volatility = std_dev / mean_price
            if relative_volatility > self.max_relative_volatility:
                continue
                
            # 2. Z-Score Band
            # Must be deep enough for value, but not so deep it indicates a collapse.
            if not (self.z_crash_guard < z_score < self.z_entry_threshold):
                continue
            
            # 3. Green Tick Confirmation (Anti-Dip-Buy-Penalty)
            # We strictly require the current price to be higher or equal to the previous tick.
            # This ensures we are buying a "Bounce" or "Pause", not an active drop.
            prev_price = history_list[-2]
            if price < prev_price:
                continue
                
            # 4. Macro Slope Check
            # Check simple return over the window to ensure we aren't in a steep cliff drop
            window_return = (price - history_list[0]) / history_list[0]
            if window_return < -0.04: # -4% in one window is too steep
                continue

            # Execute Trade
            amount = self.trade_size_usd / price
            self.positions[symbol] = {
                'entry_price': price,
                'entry_tick': self.tick_count,
                'amount': amount
            }
            
            return {
                'side': 'BUY', 
                'symbol': symbol, 
                'amount': amount, 
                'reason': ['VOL_CLAMP', f'Z:{z_score:.2f}']
            }
            
        return None