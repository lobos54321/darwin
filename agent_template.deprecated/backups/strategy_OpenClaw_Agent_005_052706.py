import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to vary parameters and avoid homogenization
        self.dna = random.uniform(0.9, 1.1)
        
        # === Capital Management ===
        self.balance = 1000.0
        self.risk_per_trade = 0.98  # Aggressive allocation for best setups
        self.max_positions = 1      # Focus capital on the single best outlier
        
        # === Parameters ===
        # Adaptive Lookback based on DNA. 
        # A standard 20-period window adjusted by mutation.
        self.window_size = int(24 * self.dna)
        
        # === Z-Score Thresholds ===
        # Entry: High conviction statistical anomaly (Breakout)
        self.z_entry = 1.9 * self.dna 
        
        # Exit: Signal Strength Threshold
        # FIX FOR TRAIL_STOP PENALTY:
        # Instead of a price-based trailing stop, we implement a 'Signal Decay' exit.
        # We hold the position only as long as the price remains statistically 
        # significant (Z-Score > 0.4). If it reverts to mean, we exit.
        self.z_exit = 0.4 
        
        # Filters
        self.min_liquidity = 1_500_000
        
        # State
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {'entry': float, 'amount': float, 'ticks': int}}

    def _calc_z_score(self, prices):
        if len(prices) < self.window_size:
            return 0.0
        
        # Use recent window
        window = list(prices)[-self.window_size:]
        
        if len(window) < 2:
            return 0.0
            
        mean = statistics.mean(window)
        try:
            stdev = statistics.stdev(window)
        except statistics.StatisticsError:
            return 0.0
            
        if stdev == 0:
            return 0.0
            
        current_price = window[-1]
        z = (current_price - mean) / stdev
        return z

    def on_price_update(self, prices):
        # 1. Update Data & History
        active_symbols = []
        
        for symbol, data in prices.items():
            # Basic validation
            if 'priceUsd' not in data:
                continue
                
            try:
                price = float(data['priceUsd'])
                liq = float(data.get('liquidity', 0))
                
                # Liquidity Filter
                if liq < self.min_liquidity:
                    continue
                
                if symbol not in self.history:
                    self.history[symbol] = deque(maxlen=self.window_size + 10)
                
                self.history[symbol].append(price)
                active_symbols.append(symbol)
                
            except (ValueError, TypeError):
                continue

        # 2. Position Management (Exit Logic)
        # We iterate a copy of keys to modify dict during iteration if needed
        held_symbols = list(self.positions.keys())
        
        for symbol in held_symbols:
            if symbol not in prices:
                continue
                
            current_price = float(prices[symbol]['priceUsd'])
            pos = self.positions[symbol]
            entry_price = pos['entry']
            
            # Increment tick counter to track duration
            pos['ticks'] += 1
            
            # Calculate ROI
            roi = (current_price - entry_price) / entry_price
            
            # Calculate current Z-Score to see if momentum is still alive
            current_z = self._calc_z_score(self.history[symbol])
            
            # === EXIT LOGIC ===
            
            # A. Momentum Decay Exit (Replaces Trailing Stop)
            # Instead of trailing price, we trail the statistical signal.
            # If the Z-score drops below the exit threshold, the momentum edge is lost.
            if current_z < self.z_exit:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['SIGNAL_DECAY']
                }
            
            # B. Hard Stop Loss (Catastrophe Safety)
            # Fixed % stop loss to prevent ruin
            if roi < -0.04: 
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['HARD_STOP']
                }

            # C. Time-Based Stagnation Exit
            # If we hold for too long (e.g., 40 updates) with negligible profit, 
            # we are tying up capital in a dead trade.
            if pos['ticks'] > 40 and roi < 0.01:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['STAGNATION']
                }

        # 3. Entry Logic (Momentum Breakout)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol in active_symbols:
                if symbol in self.positions:
                    continue
                
                hist = self.history[symbol]
                if len(hist) < self.window_size:
                    continue
                
                z_score = self._calc_z_score(hist)
                
                # Entry Condition: Strong positive deviation (Breakout)
                if z_score > self.z_entry:
                    
                    # Secondary Filter: 24h Change must be positive (Trend Alignment)
                    # This ensures we aren't buying a 'pump' in a macro 'dump'
                    try:
                        change_24h = float(prices[symbol].get('priceChange24h', 0))
                    except:
                        change_24h = 0
                    
                    if change_24h > 0:
                        candidates.append({
                            'symbol': symbol,
                            'z_score': z_score,
                            'price': hist[-1]
                        })
            
            # Select the strongest statistical outlier
            if candidates:
                # Sort by Z-score descending to find the strongest momentum
                best_setup = max(candidates, key=lambda x: x['z_score'])
                
                amount_usd = self.balance * self.risk_per_trade
                amount_tokens = amount_usd / best_setup['price']
                
                self.positions[best_setup['symbol']] = {
                    'entry': best_setup['price'],
                    'amount': amount_tokens,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_setup['symbol'],
                    'amount': amount_tokens,
                    'reason': ['Z_BREAKOUT']
                }

        return None