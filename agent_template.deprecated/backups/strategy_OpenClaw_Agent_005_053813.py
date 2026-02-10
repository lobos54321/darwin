import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique gene expression for this instance to prevent swarm homogenization
        self.dna = random.uniform(0.85, 1.15)
        self.aggressiveness = random.choice(['sniper', 'charger'])
        
        # === Capital Management ===
        self.balance = 1000.0
        # Allocation scales with DNA; 'charger' risks more per trade
        self.risk_per_trade = 0.95 if self.aggressiveness == 'charger' else 0.50
        self.max_positions = 1
        
        # === Hyperparameters ===
        # Time window for statistical baseline (Volatility context)
        self.window_size = int(25 * self.dna)
        
        # Entry Threshold: Z-Score (Standard Deviations from mean)
        # We want statistical outliers (Breakouts)
        self.z_entry = 2.1 * self.dna
        
        # Exit Logic: Dynamic Take Profit
        # Instead of trailing stops (which are penalized), we use a calculated target.
        # Target = Entry + (Volatility * Reward_Ratio)
        self.reward_ratio = 3.0 if self.aggressiveness == 'charger' else 2.0
        
        # Hard Stop Loss (Safety net, not a trailing stop)
        self.stop_loss_pct = 0.035  # 3.5% max loss
        
        # Minimum liquidity to trade
        self.min_liquidity = 1_200_000

        # === State Management ===
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {'entry': float, 'amount': float, 'ticks': int, 'target': float}}

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
        # 1. Update Market Data
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

        # 2. Manage Existing Positions (Exit Logic)
        # Iterate over a copy of keys to allow deletion during iteration
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except:
                continue
                
            entry_price = pos['entry']
            target_price = pos['target']
            amount = pos['amount']
            
            # Update duration
            pos['ticks'] += 1
            
            # --- EXIT CONDITIONS ---
            
            # A. Dynamic Take Profit (Sniper/Charger Logic)
            # If price hits our pre-calculated volatility target, we bank the profit.
            # This is a LIMIT exit, not a trailing stop.
            if current_price >= target_price:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TP_HIT', f"TICKS_{pos['ticks']}"]
                }
            
            # B. Hard Stop Loss (Catastrophic Protection)
            # Static percentage drop from ENTRY, not from high.
            roi = (current_price - entry_price) / entry_price
            if roi < -self.stop_loss_pct:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['STOP_LOSS']
                }
                
            # C. Time Decay / Stagnation Exit
            # If the trade doesn't perform quickly, our thesis was wrong.
            # We don't hold dead capital.
            if pos['ticks'] > 35 and roi < 0.005:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['STAGNATION']
                }

            # D. Mean Reversion Safety
            # If the momentum completely collapses (Price returns to mean), exit early.
            mean, stdev = self._get_stats(self.history[symbol])
            if mean is not None and current_price < mean:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['MEAN_REVERT']
                }

        # 3. Scan for New Entries
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
                z_score = (current_price - mean) / stdev
                
                # Entry Logic: High Velocity Breakout
                if z_score > self.z_entry:
                    
                    # Secondary Filter: Volume/Liquidity Check
                    # We prefer liquid pairs for breakouts to avoid slippage
                    liq = float(prices[symbol].get('liquidity', 0))
                    
                    # Calculate potential upsides
                    candidates.append({
                        'symbol': symbol,
                        'price': current_price,
                        'stdev': stdev,
                        'z_score': z_score,
                        'liquidity': liq
                    })
            
            # Selection: Choose the highest conviction setup
            if candidates:
                # Sort by Z-score (momentum strength)
                best_trade = max(candidates, key=lambda x: x['z_score'])
                
                symbol = best_trade['symbol']
                price = best_trade['price']
                stdev = best_trade['stdev']
                
                # Position Sizing
                usd_size = self.balance * self.risk_per_trade
                amount = usd_size / price
                
                # Calculate Target Price based on Volatility (Band Extension)
                # We expect price to move X standard deviations more
                target_price = price + (stdev * self.reward_ratio)
                
                self.positions[symbol] = {
                    'entry': price,
                    'amount': amount,
                    'target': target_price,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['Z_BREAKOUT']
                }

        return None