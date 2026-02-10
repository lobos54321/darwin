import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Randomize parameters to prevent swarm homogenization
        self.dna = random.uniform(0.9, 1.1)
        self.risk_profile = random.choice(['conservative', 'aggressive'])
        
        # === Capital Management ===
        self.balance = 1000.0
        self.risk_per_trade = 0.98 if self.risk_profile == 'aggressive' else 0.45
        self.max_positions = 1
        
        # === Hyperparameters ===
        # We pivot from Breakout (Penalized) to Mean Reversion (Dip Buying)
        # Window size adapted by DNA
        self.window_size = int(20 * self.dna)
        
        # Entry Threshold: Negative Z-Score (Buying the Dip)
        # We buy when price is significantly below the mean
        self.z_entry = -2.2 * self.dna 
        
        # Safety: Maximum Volatility allowed to enter (avoid catching falling knives)
        self.max_volatility_pct = 0.05 
        
        # Exit Logic: Mean Reversion
        # We target a return to the mean, not an arbitrary profit target
        
        # Hard Stop Loss (Static % from entry)
        self.stop_loss_pct = 0.04  # 4% max loss
        
        # Minimum liquidity filter
        self.min_liquidity = 1_500_000

        # === State Management ===
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {'entry': float, 'amount': float, 'ticks': int}}

    def _get_stats(self, prices):
        """Calculates Mean and Standard Deviation for the window."""
        if len(prices) < self.window_size:
            return None, None
            
        window = list(prices)[-self.window_size:]
        if len(window) < 2:
            return None, None
            
        try:
            mean = statistics.mean(window)
            stdev = statistics.stdev(window)
            return mean, stdev
        except statistics.StatisticsError:
            return None, None

    def on_price_update(self, prices):
        # 1. Update Market Data & History
        active_symbols = []
        
        for symbol, data in prices.items():
            if 'priceUsd' not in data:
                continue
            
            try:
                current_price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
                
                # Liquidity Filter
                if liquidity < self.min_liquidity:
                    continue
                
                if symbol not in self.history:
                    self.history[symbol] = deque(maxlen=self.window_size + 5)
                
                self.history[symbol].append(current_price)
                active_symbols.append(symbol)
                
            except (ValueError, TypeError):
                continue

        # 2. Manage Existing Positions
        # Iterate over a copy to allow deletion
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except:
                continue
                
            entry_price = pos['entry']
            amount = pos['amount']
            pos['ticks'] += 1
            
            # Update stats to check for mean reversion
            hist = self.history.get(symbol)
            mean, stdev = (None, None)
            if hist:
                mean, stdev = self._get_stats(hist)

            # --- EXIT CONDITIONS ---
            
            # A. Mean Reversion Target (Take Profit)
            # If price returns to (or crosses) the moving average, the edge is gone.
            # We exit immediately.
            if mean is not None and current_price >= mean:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['RETURN_TO_MEAN']
                }
            
            # B. Hard Stop Loss
            # Fixed percentage. No trailing.
            roi = (current_price - entry_price) / entry_price
            if roi < -self.stop_loss_pct:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['STOP_LOSS']
                }
                
            # C. Time Decay
            # If mean reversion doesn't happen quickly, statistically it's less likely to happen.
            if pos['ticks'] > 40:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['STALE_TRADE']
                }

        # 3. Scan for New Entries (Buying Dips)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol in active_symbols:
                if symbol in self.positions:
                    continue
                    
                hist = self.history[symbol]
                mean, stdev = self._get_stats(hist)
                
                if mean is None or stdev == 0:
                    continue
                    
                current_price = hist[-1]
                
                # Calculate Volatility %
                volatility_pct = stdev / mean
                
                # Filter: Don't trade if volatility is too extreme (crash risk)
                if volatility_pct > self.max_volatility_pct:
                    continue
                
                z_score = (current_price - mean) / stdev
                
                # Entry Logic: Deep Dip (Negative Z-Score)
                # This fixes 'Z_BREAKOUT' by inverting the logic to Mean Reversion
                if z_score < self.z_entry:
                    
                    candidates.append({
                        'symbol': symbol,
                        'price': current_price,
                        'z_score': z_score, # deeper is better (more negative)
                        'mean': mean
                    })
            
            # Selection: Choose the most oversold asset
            if candidates:
                # Sort by Z-score ascending (most negative first)
                best_trade = min(candidates, key=lambda x: x['z_score'])
                
                symbol = best_trade['symbol']
                price = best_trade['price']
                
                # Position Sizing
                usd_size = self.balance * self.risk_per_trade
                amount = usd_size / price
                
                self.positions[symbol] = {
                    'entry': price,
                    'amount': amount,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['OVERSOLD_DIP']
                }

        return None