import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique seed to diversify strategy behavior and avoid swarm correlation
        self.dna = random.random()
        
        # === Parameters ===
        self.virtual_balance = 1000.0
        
        # Mutated Window Size (20-30 ticks)
        self.window_size = 20 + int(self.dna * 10)
        
        # Strict Entry Logic (Fixing DIP_BUY & Z_BREAKOUT)
        # We only buy DEEP statistical deviations.
        # Z-Score threshold: -2.5 to -3.5 (based on DNA)
        self.z_thresh = -2.5 - (self.dna * 1.0)
        
        # RSI threshold: 25-30 (Oversold)
        self.rsi_thresh = 25 + int(self.dna * 5)
        
        # Exit Logic (Fixing FIXED_TP & TRAIL_STOP)
        # Stop Loss Multiplier (Fixed at entry)
        self.stop_mult = 3.0 + (self.dna * 1.5)
        
        # Filters (Fixing ER:0.004)
        # Minimum potential profit (distance to EMA) to justify entry
        self.min_edge_pct = 0.006 + (self.dna * 0.002) 
        self.min_volatility = 0.005
        self.min_liquidity = 1_000_000
        
        # === State ===
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {'entry': float, 'stop': float, 'amount': float, 'ticks': int}}
        self.cooldowns = {}     # {symbol: int}

    def _get_indicators(self, prices_deque):
        """Calculates Z-Score, EMA, RSI, and Volatility."""
        if len(prices_deque) < self.window_size:
            return None
        
        data = list(prices_deque)
        
        # 1. EMA (Exponential Moving Average)
        # Alpha tuned for responsiveness
        k = 2 / (self.window_size + 1)
        ema = data[0]
        for p in data[1:]:
            ema = (p * k) + (ema * (1 - k))
            
        # 2. Volatility (Standard Deviation)
        # We use simple population std dev relative to EMA for speed
        variance = sum((x - ema) ** 2 for x in data) / len(data)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0:
            return None
            
        # 3. Z-Score (Current price deviation from mean)
        current_price = data[-1]
        z_score = (current_price - ema) / std_dev
        
        # 4. RSI (Relative Strength Index)
        gains = 0
        losses = 0
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            else:
                losses -= change
                
        if losses == 0:
            rsi = 100
        else:
            rs = gains / losses
            rsi = 100 - (100 / (1 + rs))
            
        return {
            'ema': ema,
            'std_dev': std_dev,
            'z_score': z_score,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        """
        Core Logic:
        1. Parse Data
        2. Check Exits (Fixed Stop, Dynamic TP)
        3. Check Entries (Deep Dip + Confluence)
        """
        
        # 1. Manage Cooldowns
        active_cooldowns = list(self.cooldowns.keys())
        for sym in active_cooldowns:
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Data Ingestion & Metric Calculation
        candidates = []
        
        for symbol, data in prices.items():
            try:
                # Strict type casting
                price = float(data['priceUsd'])
                liq = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
                
            if liq < self.min_liquidity:
                continue
                
            # Maintain History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            # Need full window for valid stats
            if len(self.history[symbol]) < self.window_size:
                continue
            
            # Calculate Indicators
            stats = self._get_indicators(self.history[symbol])
            if not stats:
                continue
            
            # Volatility Filter (Fixing ER:0.004)
            # Ensure price is moving enough to cover fees
            if (stats['std_dev'] / price) < self.min_volatility:
                continue
                
            candidates.append({
                'symbol': symbol,
                'price': price,
                'stats': stats
            })

        # 3. Position Management (Exits)
        # Only holding 1 position max, but logic supports multiple if needed
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            curr_price = float(prices[symbol]['priceUsd'])
            pos['ticks'] += 1
            
            # Retrieve updated stats if available
            cand = next((c for c in candidates if c['symbol'] == symbol), None)
            
            # --- EXIT: Fixed Stop Loss (Fixing TRAIL_STOP) ---
            # We respect the stop price calculated at entry. No trailing.
            if curr_price <= pos['stop']:
                del self.positions[symbol]
                self.cooldowns[symbol] = 20 # Penalty box
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['FIXED_STOP']
                }
            
            # --- EXIT: Dynamic Take Profit (Fixing FIXED_TP) ---
            # We exit if price reverts to Mean (EMA) or momentum exhausts (RSI high)
            if cand:
                stats = cand['stats']
                ema = stats['ema']
                rsi = stats['rsi']
                
                # Condition 1: Mean Reversion (Price touched EMA)
                # Condition 2: Overbought Spike (RSI > 70)
                # Condition 3: Time limit (Stale trade)
                
                # Check profitability to cover fees
                is_profitable = curr_price > (pos['entry'] * 1.002)
                
                should_tp = (curr_price >= ema) or (rsi > 70)
                
                if should_tp and is_profitable:
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': pos['amount'],
                        'reason': ['DYNAMIC_TP']
                    }
                    
            # --- EXIT: Time Expiry ---
            if pos['ticks'] > 50:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['TIME_LIMIT']
                }

        # 4. Entry Logic
        # Only enter if no position held
        if len(self.positions) == 0:
            best_setup = None
            lowest_z = 0
            
            for c in candidates:
                sym = c['symbol']
                if sym in self.cooldowns:
                    continue
                    
                stats = c['stats']
                price = c['price']
                
                # --- FILTER: Edge Ratio (ER:0.004) ---
                # Calculate distance to EMA. If potential reward is too small, skip.
                potential_reward_pct = (stats['ema'] - price) / price
                if potential_reward_pct < self.min_edge_pct:
                    continue

                # --- ENTRY: Confluence Dip ---
                # 1. Deep Statistical Dip (Z-Score < Threshold)
                # 2. Momentum Oversold (RSI < Threshold)
                if stats['z_score'] < self.z_thresh and stats['rsi'] < self.rsi_thresh:
                    # Score candidates by depth of dip (Z-Score)
                    if stats['z_score'] < lowest_z:
                        lowest_z = stats['z_score']
                        best_setup = c
            
            if best_setup:
                target_sym = best_setup['symbol']
                entry_price = best_setup['price']
                stats = best_setup['stats']
                
                amount = self.virtual_balance / entry_price
                
                # Calculate FIXED Stop Loss
                # Based on volatility at moment of entry
                stop_dist = stats['std_dev'] * self.stop_mult
                stop_price = entry_price - stop_dist
                
                # Sanity check stop
                if stop_price <= 0: stop_price = entry_price * 0.8
                
                self.positions[target_sym] = {
                    'entry': entry_price,
                    'stop': stop_price,
                    'amount': amount,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': target_sym,
                    'amount': amount,
                    'reason': ['DEEP_DIP_Z']
                }
                
        return None