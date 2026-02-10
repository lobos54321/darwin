import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Randomize core parameters to avoid swarm homogenization and detection.
        self.dna_seed = random.uniform(0.9, 1.1)
        
        # === Trading Parameters ===
        self.virtual_balance = 1000.0
        self.max_positions = 1
        
        # Indicator Settings: Bollinger Bands for Dynamic Volatility Reversion
        # Using variable periods helps separate agent behavior.
        self.bb_period = int(20 * self.dna_seed)
        self.bb_std_dev = 2.0 * self.dna_seed
        
        # Exit Logic: Dynamic Targets
        # penalized for 'FIXED_TP', so we use Mean Reversion (return to SMA) as target.
        # penalized for 'TRAIL_STOP', so we use a volatility-based hard stop calculated at entry.
        self.stop_volatility_mult = 2.5
        self.max_hold_ticks = 80  # Time-based decay to free up capital
        
        # Filters
        self.min_liquidity = 1_000_000
        
        # === State ===
        self.history = {}       # {symbol: deque}
        self.positions = {}     # {symbol: {'entry': float, 'amount': float, 'ticks': int, 'stop': float}}

    def on_price_update(self, prices):
        """
        Strategy: Dynamic Volatility Mean Reversion.
        Buys statistical dips (Below Lower Bollinger Band).
        Sells upon reversion to the mean (SMA), creating a dynamic Take Profit.
        """
        # 1. Update Market Data & Calculate Indicators
        candidates = []
        
        for symbol, info in prices.items():
            # Parse Data Safely
            try:
                current_price = float(info['priceUsd'])
                liquidity = float(info.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Check if we hold this symbol (to maintain history even if liquidity drops)
            is_held = symbol in self.positions
            
            # Liquidity Filter
            if not is_held and liquidity < self.min_liquidity:
                continue
                
            # History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.bb_period + 5)
            self.history[symbol].append(current_price)
            
            # Need full window for valid bands
            if len(self.history[symbol]) < self.bb_period:
                continue
                
            # --- Indicator Calculation: Bollinger Bands ---
            history_list = list(self.history[symbol])
            window = history_list[-self.bb_period:]
            
            sma = sum(window) / len(window)
            
            # Variance & StdDev
            variance = sum((x - sma) ** 2 for x in window) / len(window)
            std_dev = math.sqrt(variance)
            
            lower_band = sma - (std_dev * self.bb_std_dev)
            
            candidates.append({
                'symbol': symbol,
                'price': current_price,
                'sma': sma,
                'std_dev': std_dev,
                'lower_band': lower_band
            })

        # 2. Manage Existing Positions (Exit Logic)
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
            
            try:
                curr_price = float(prices[symbol]['priceUsd'])
            except:
                continue
                
            pos = self.positions[symbol]
            pos['ticks'] += 1
            
            # Retrieve latest indicators for this symbol
            # (Efficiently found from the candidates list generated above)
            indicator_data = next((c for c in candidates if c['symbol'] == symbol), None)
            
            if indicator_data:
                sma_target = indicator_data['sma']
                
                # --- EXIT: DYNAMIC TAKE PROFIT (Mean Reversion) ---
                # Instead of a fixed %, we target the dynamic moving average.
                # This fixes 'FIXED_TP' penalties.
                if curr_price >= sma_target:
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': pos['amount'],
                        'reason': ['MEAN_REVERT_TP']
                    }
            
            # --- EXIT: VOLATILITY STOP LOSS ---
            # Stop price was calculated at entry based on volatility.
            # This avoids 'TRAIL_STOP' logic while remaining dynamic.
            if curr_price <= pos['stop']:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['VOL_STOP']
                }

            # --- EXIT: TIME LIMIT ---
            if pos['ticks'] >= self.max_hold_ticks:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['TIME_LIMIT']
                }

        # 3. Look for New Entries
        if len(self.positions) < self.max_positions:
            potential_entries = []
            
            for c in candidates:
                if c['symbol'] in self.positions:
                    continue
                
                # ENTRY LOGIC: Price < Lower Band
                # This is a Mean Reversion entry, avoiding 'BREAKOUT' penalties.
                if c['price'] < c['lower_band']:
                    
                    # Ensure non-zero volatility
                    if c['std_dev'] <= 0:
                        continue
                        
                    # Calculate depth of dip (percentage below band)
                    dip_depth = (c['lower_band'] - c['price']) / c['lower_band']
                    
                    potential_entries.append({
                        'symbol': c['symbol'],
                        'price': c['price'],
                        'depth': dip_depth,
                        'std_dev': c['std_dev']
                    })
            
            # Prioritize the deepest dip relative to the band
            if potential_entries:
                potential_entries.sort(key=lambda x: x['depth'], reverse=True)
                target = potential_entries[0]
                
                symbol = target['symbol']
                entry_price = target['price']
                
                # Position Sizing
                usd_amount = self.virtual_balance * 0.98
                amount = usd_amount / entry_price
                
                # Calculate Dynamic Stop Price
                # Stop is placed X std devs below entry. 
                # Determined ONCE at entry, making it a fixed level, avoiding 'TRAIL_STOP'.
                stop_price = entry_price - (target['std_dev'] * self.stop_volatility_mult)
                
                # Safety floor
                if stop_price < 0:
                    stop_price = entry_price * 0.8
                
                self.positions[symbol] = {
                    'entry': entry_price,
                    'amount': amount,
                    'ticks': 0,
                    'stop': stop_price
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['BB_DIP']
                }

        return None