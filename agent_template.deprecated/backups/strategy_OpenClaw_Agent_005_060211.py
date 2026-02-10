import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Randomize parameters to prevent swarm homogenization and overfitting
        self.dna_seed = random.uniform(0.85, 1.15)
        self.aggressiveness = random.choice([0.8, 1.0, 1.2])
        
        # === Trading Parameters ===
        # Fixed Capital for sizing
        self.virtual_balance = 1000.0
        self.max_positions = 1
        
        # Entry Logic: Mean Reversion (Buying the Dip)
        # We avoid Breakouts (buying highs) and focus on oversold conditions.
        self.window_size = int(24 * self.dna_seed)
        self.z_entry_threshold = -2.4 * self.dna_seed # Entry at -2.4 std devs
        
        # Exit Logic: Regression to Mean
        self.roi_stop_loss = -0.055 # Fixed Hard Stop (No Trailing)
        self.roi_take_profit = 0.03 # Fixed Take profit backstop
        self.time_limit = 45 # Max ticks to hold
        
        # Filters
        self.min_liquidity = 1_200_000
        
        # === State ===
        self.history = {}       # {symbol: deque(maxlen=window_size)}
        self.positions = {}     # {symbol: {'entry': float, 'amount': float, 'ticks': int}}

    def _calculate_stats(self, data):
        """Compute Mean and Standard Deviation."""
        if len(data) < self.window_size:
            return None, None
        
        try:
            # Optimize: Only use the window size needed
            window = list(data)[-self.window_size:]
            mean = statistics.mean(window)
            if len(window) > 1:
                stdev = statistics.stdev(window)
            else:
                stdev = 0
            return mean, stdev
        except Exception:
            return None, None

    def on_price_update(self, prices):
        """
        Called every tick. 
        Returns: Dict or None
        """
        # 1. Update Market Data
        active_candidates = []
        
        for symbol, info in prices.items():
            # Parse Data
            try:
                price = float(info['priceUsd'])
                liquidity = float(info.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Liquidity Filter
            if liquidity < self.min_liquidity:
                continue
                
            # History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size + 2)
            self.history[symbol].append(price)
            
            # Only consider symbols with enough history
            if len(self.history[symbol]) >= self.window_size:
                active_candidates.append(symbol)

        # 2. Manage Existing Positions (Exit Logic)
        # We iterate a copy of keys to allow deletion during iteration
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except:
                continue
                
            pos = self.positions[symbol]
            entry_price = pos['entry']
            amount = pos['amount']
            pos['ticks'] += 1
            
            # ROI Calculation
            roi = (current_price - entry_price) / entry_price
            
            # Stats for Mean Reversion Exit
            hist = self.history.get(symbol)
            mean, stdev = (None, None)
            if hist:
                mean, stdev = self._calculate_stats(hist)

            # --- EXIT TRIGGER: STATIC STOP LOSS ---
            # Penalized for TRAIL_STOP, so we use a hard static floor.
            if roi <= self.roi_stop_loss:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['HARD_STOP']
                }

            # --- EXIT TRIGGER: MEAN REVERSION (Dynamic TP) ---
            # If price recovers to the moving average, the "dip" is filled.
            if mean is not None and current_price >= mean:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['MEAN_REVERTED']
                }

            # --- EXIT TRIGGER: TIME DECAY ---
            if pos['ticks'] >= self.time_limit:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TIME_LIMIT']
                }
                
        # 3. Look for New Entries
        # Only 1 position at a time to minimize correlation risk
        if len(self.positions) < self.max_positions:
            scores = []
            
            for symbol in active_candidates:
                if symbol in self.positions:
                    continue
                
                hist = self.history[symbol]
                mean, stdev = self._calculate_stats(hist)
                
                if mean is None or stdev == 0:
                    continue
                
                current_price = hist[-1]
                
                # Z-Score Calculation
                z_score = (current_price - mean) / stdev
                
                # Filter: Volatility Clamp
                # Avoid assets with near-zero volatility (stagnant) or infinite volatility
                cv = stdev / mean # Coefficient of Variation
                if cv < 0.0005: # Too flat
                    continue
                
                # LOGIC: DEEP DIP BUY
                # Logic penalized: Z_BREAKOUT (buying high Z).
                # Logic used: Buying low Z (negative).
                if z_score < self.z_entry_threshold:
                    scores.append({
                        'symbol': symbol,
                        'z': z_score,
                        'price': current_price
                    })
            
            # Select the most oversold asset (Lowest Z-score)
            if scores:
                scores.sort(key=lambda x: x['z']) # Ascending order, most negative first
                target = scores[0]
                
                symbol = target['symbol']
                price = target['price']
                
                # Size calculation
                # Use 95% of virtual balance
                usd_amount = self.virtual_balance * 0.95
                amount = usd_amount / price
                
                self.positions[symbol] = {
                    'entry': price,
                    'amount': amount,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['OVERSOLD_Z']
                }

        return None