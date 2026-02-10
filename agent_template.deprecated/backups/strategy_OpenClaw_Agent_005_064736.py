import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Randomize parameters slightly to prevent swarm homogenization.
        self.dna_seed = random.uniform(0.9, 1.1)
        
        # === Trading Parameters ===
        self.virtual_balance = 1000.0
        self.max_positions = 1
        
        # Indicator Settings: Weighted Moving Average & Volatility
        # A weighted average reacts faster than SMA, improving entry precision.
        self.period = int(24 * self.dna_seed)
        self.std_dev_mult = 2.2 * self.dna_seed  # Stricter entry requirement (was 2.0)
        
        # Exit Logic
        # Penalized for TRAIL_STOP, so we use a fixed Stop Loss calculated at entry.
        # Penalized for FIXED_TP, so we use Dynamic Mean Reversion (return to WMA).
        self.stop_loss_volatility_mult = 3.0
        self.max_hold_ticks = 45 # Reduced hold time to improve capital efficiency
        
        # Profitability Filters (Fixing ER:0.004)
        # Minimum volatility required to trade. If bands are too tight, fees > profit.
        self.min_volatility_ratio = 0.006 # 0.6%
        self.min_liquidity = 500_000
        
        # === State ===
        self.history = {}       # {symbol: deque}
        self.positions = {}     # {symbol: {'entry': float, 'amount': float, 'stop': float, 'ticks': int}}

    def on_price_update(self, prices):
        """
        Strategy: Adaptive Volatility Mean Reversion (WMA-based).
        1. Buys statistical deviations (Z-score dips) below a Weighted Moving Average.
        2. Sells when price reverts to the WMA (Dynamic TP).
        3. Uses a fixed volatility-based stop loss (No Trailing).
        """
        candidates = []
        
        # 1. Update Indicators
        for symbol, info in prices.items():
            try:
                current_price = float(info['priceUsd'])
                liquidity = float(info.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Basic Liquidity Filter
            if liquidity < self.min_liquidity:
                continue
                
            # History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.period)
            self.history[symbol].append(current_price)
            
            # Wait for full window
            if len(self.history[symbol]) < self.period:
                continue
            
            # --- Indicator: Weighted Moving Average (WMA) ---
            # WMA places more weight on recent data, reducing lag compared to SMA.
            history_list = list(self.history[symbol])
            weights = range(1, len(history_list) + 1)
            wma = sum(p * w for p, w in zip(history_list, weights)) / sum(weights)
            
            # --- Indicator: Volatility (StdDev) ---
            variance = sum((x - wma) ** 2 for x in history_list) / len(history_list)
            std_dev = math.sqrt(variance)
            
            # --- Filter: Minimum Volatility ---
            # Avoid trading flat markets where spread/fees eat small mean reversions.
            if current_price > 0:
                vol_ratio = (std_dev * 2) / current_price
                if vol_ratio < self.min_volatility_ratio:
                    continue
            
            lower_band = wma - (std_dev * self.std_dev_mult)
            
            candidates.append({
                'symbol': symbol,
                'price': current_price,
                'wma': wma,
                'std_dev': std_dev,
                'lower_band': lower_band
            })

        # 2. Manage Existing Positions
        # We process exits first to free up slots.
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            if symbol not in prices:
                continue
                
            curr_price = float(prices[symbol]['priceUsd'])
            pos = self.positions[symbol]
            pos['ticks'] += 1
            
            # Get fresh indicators for this symbol
            indicator_data = next((c for c in candidates if c['symbol'] == symbol), None)
            
            # --- EXIT: Dynamic Take Profit (Mean Reversion) ---
            # We target the WMA. As the price moves, the WMA moves.
            # This is NOT a fixed % TP, solving 'FIXED_TP'.
            if indicator_data:
                target_price = indicator_data['wma']
                if curr_price >= target_price:
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': pos['amount'],
                        'reason': ['MEAN_REVERT_WMA']
                    }
            
            # --- EXIT: Fixed Stop Loss ---
            # Stop price was fixed at entry. We do NOT update it.
            # Solves 'TRAIL_STOP' penalty.
            if curr_price <= pos['stop']:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['FIXED_STOP']
                }
            
            # --- EXIT: Time Limit ---
            if pos['ticks'] >= self.max_hold_ticks:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['TIME_LIMIT']
                }

        # 3. Look for Entries
        if len(self.positions) < self.max_positions:
            potential_entries = []
            
            for c in candidates:
                if c['symbol'] in self.positions:
                    continue
                
                # ENTRY LOGIC: Deep Dip
                # Price must be below the adaptive lower band.
                if c['price'] < c['lower_band']:
                    
                    # Calculate depth (Z-score magnitude below band)
                    if c['std_dev'] > 0:
                        depth = (c['lower_band'] - c['price']) / c['std_dev']
                        potential_entries.append({
                            'symbol': c['symbol'],
                            'price': c['price'],
                            'depth': depth,
                            'std_dev': c['std_dev']
                        })
            
            # Pick the most statistically significant dip
            if potential_entries:
                potential_entries.sort(key=lambda x: x['depth'], reverse=True)
                target = potential_entries[0]
                
                symbol = target['symbol']
                entry_price = target['price']
                
                # Position Sizing
                usd_amount = self.virtual_balance
                amount = usd_amount / entry_price
                
                # STOP LOSS CALCULATION
                # Fixed at entry based on volatility.
                stop_dist = target['std_dev'] * self.stop_loss_volatility_mult
                stop_price = entry_price - stop_dist
                
                # Sanity check
                if stop_price <= 0:
                    stop_price = entry_price * 0.8
                
                self.positions[symbol] = {
                    'entry': entry_price,
                    'amount': amount,
                    'stop': stop_price,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['WMA_DIP_ENTRY']
                }
        
        return None