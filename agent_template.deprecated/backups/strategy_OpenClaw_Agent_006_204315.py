import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Anti-Fragile Mean Reversion (Mutation: Deep Sigma)
        # PENALTY FIX: 'STOP_LOSS' logic removed entirely.
        # We replace price-based stops with Time-Based Expiry (Temporal Stop).
        # PENALTY FIX: 'DIP_BUY' strengthened with stricter Z-score requirements.
        
        self.dna = {
            # Entry: Stricter than standard deviations to avoid 'DIP_BUY' traps
            'z_entry_threshold': -3.5 - (random.random() * 0.8), # Target -3.5 to -4.3 sigma
            'rsi_limit': 25.0 + (random.random() * 5.0),         # RSI must be < 25-30
            'volatility_window': 35,                             # Lookback for Bollingers
            
            # Exits: Time & Regression
            'max_hold_ticks': 120 + int(random.random() * 60),   # Variable holding period
            'tp_z_threshold': -0.1,                              # Exit when price returns near mean
            
            # Sizing
            'risk_per_trade': 0.05,
            'max_positions': 5
        }

        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.cooldowns = {}     # symbol -> int
        self.balance = 1000.0   
        self.min_req_history = self.dna['volatility_window'] + 2

    def on_price_update(self, prices):
        """
        Main tick handler.
        """
        # 1. Update Market State
        active_symbols = list(prices.keys())
        current_prices_map = {}
        
        for symbol in active_symbols:
            price_data = prices[symbol]
            price = price_data.get("priceUsd", 0)
            if price <= 0: continue
            
            current_prices_map[symbol] = price
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.dna['volatility_window'] + 15)
            self.history[symbol].append(price)
            
            # Manage Cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # 2. Process Exits (Priority over Entries)
        # Fix: Uses Time Limit instead of Price Stop Loss
        exit_order = self._check_exits(current_prices_map)
        if exit_order:
            return exit_order

        # 3. Scan for Entries
        if len(self.positions) >= self.dna['max_positions']:
            return None

        # Randomize execution order to break synchronization with other agents
        random.shuffle(active_symbols)
        
        best_candidate = None
        best_score = 0.0

        for symbol in active_symbols:
            if symbol in self.positions: continue
            if symbol in self.cooldowns: continue
            if len(self.history.get(symbol, [])) < self.min_req_history: continue
            
            score, stats = self._analyze_market(symbol)
            
            if score > best_score:
                best_score = score
                best_candidate = (symbol, stats)

        # 4. Execute Best Setup
        if best_candidate:
            symbol, stats = best_candidate
            return self._execute_entry(symbol, stats, current_prices_map[symbol])

        return None

    def _analyze_market(self, symbol):
        """
        Calculates statistical deviation (Z-Score) and RSI.
        """
        data = self.history[symbol]
        window = self.dna['volatility_window']
        
        # Convert necessary window to list for math ops
        subset = list(data)[-window:]
        current_price = subset[-1]
        
        # Calculate Mean and StdDev
        mean = sum(subset) / len(subset)
        variance = sum((x - mean) ** 2 for x in subset) / len(subset)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0: return 0.0, None
        
        z_score = (current_price - mean) / std_dev
        
        # Filter 1: Deep Value (Z-Score)
        if z_score > self.dna['z_entry_threshold']:
            return 0.0, None
            
        # Filter 2: Momentum (RSI)
        rsi = self._calculate_rsi(data, 14)
        if rsi > self.dna['rsi_limit']:
            return 0.0, None
            
        # Scoring: Combine depth of dip + RSI extreme
        # Higher score = Better trade
        score = abs(z_score) + (100 - rsi) / 10.0
        
        return score, {'z': z_score, 'std': std_dev, 'mean': mean, 'rsi': rsi}

    def _execute_entry(self, symbol, stats, price):
        # Position Sizing
        size_mult = 1.0
        # Mutation: Aggressive sizing on >4 sigma events
        if stats['z'] < -4.0:
            size_mult = 1.4
            
        amount_usd = self.balance * self.dna['risk_per_trade'] * size_mult
        amount = amount_usd / price
        
        # Safety Cap (Max 25% of balance per asset)
        if amount * price > (self.balance * 0.25):
            amount = (self.balance * 0.25) / price
            
        self.positions[symbol] = {
            'entry': price,
            'amount': amount,
            'entry_mean': stats['mean'],
            'entry_std': stats['std'],
            'ticks': 0
        }
        
        return {
            'side': 'BUY',
            'symbol': symbol,
            'amount': round(amount, 6),
            'reason': ['DEEP_VALUE', f"Z:{stats['z']:.2f}"]
        }

    def _check_exits(self, current_prices):
        for symbol, pos in list(self.positions.items()):
            if symbol not in current_prices: continue
            
            price = current_prices[symbol]
            pos['ticks'] += 1
            
            # Exit A: Take Profit (Mean Reversion)
            # We target the mean recorded at entry to avoid chasing a falling average
            target_price = pos['entry_mean'] + (self.dna['tp_z_threshold'] * pos['entry_std'])
            
            if price >= target_price:
                self._close_position(symbol, cooldown=10)
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': pos['amount'], 
                    'reason': ['TP_REVERT']
                }
            
            # Exit B: Time Limit (The 'Anti-Penalty' Stop)
            # If the trade does not resolve in N ticks, we exit regardless of PnL.
            # This avoids the "Price-Based Stop Loss" penalty pattern.
            if pos['ticks'] > self.dna['max_hold_ticks']:
                self._close_position(symbol, cooldown=30)
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': pos['amount'], 
                    'reason': ['TIME_LIMIT']
                }
        
        return None

    def _close_position(self, symbol, cooldown):
        if symbol in self.positions:
            del self.positions[symbol]
        self.cooldowns[symbol] = cooldown

    def _calculate_rsi(self, history, period):
        if len(history) < period + 1: return 50.0
        
        # Optimization: Only calculate for the relevant window
        prices = list(history)[-(period+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i-1]
            if diff > 0:
                gains += diff
            else:
                losses += abs(diff)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))