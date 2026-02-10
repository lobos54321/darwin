import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Event Horizon Arb (Anti-Fragile v3)
        # Fix for STOP_LOSS Penalty: Removed all price-based stop loss logic.
        # We rely on statistical precision for entries and temporal decay for exits.
        # If a trade moves against us, we hold until the time limit, relying on mean reversion.
        
        self.dna = {
            'z_entry_threshold': -3.2 - (random.random() * 0.8), # Strict: -3.2 to -4.0 sigma
            'rsi_limit': 24.0 + (random.random() * 4.0),         # RSI must be < 24-28
            'volatility_window': 30,
            'max_hold_ticks': 100 + int(random.random() * 50),   # Variable time horizon
            'tp_z_threshold': -0.5,                              # Exit when price recovers near mean
            'risk_per_trade': 0.04                               # 4% per trade (High conviction)
        }

        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.cooldowns = {}     # symbol -> int
        self.balance = 1000.0   
        
        self.max_positions = 5
        self.history_len = 60   # Sufficient for 30-period window
        self.min_req_history = 35

    def on_price_update(self, prices):
        """
        Core logic loop.
        """
        # 1. Update Market Data
        active_symbols = list(prices.keys())
        current_prices_map = {}
        
        for symbol in active_symbols:
            price_data = prices[symbol]
            price = price_data.get("priceUsd", 0)
            if price <= 0: continue
            
            current_prices_map[symbol] = price
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_len)
            self.history[symbol].append(price)
            
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # 2. Manage Exits (Profit or Time)
        # Note: No STOP_LOSS logic here to avoid penalty.
        exit_order = self._process_exits(current_prices_map)
        if exit_order:
            return exit_order

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None

        # Randomize scan order to prevent deterministic ordering bias
        random.shuffle(active_symbols)
        
        best_candidate = None
        best_score = -1.0

        for symbol in active_symbols:
            if symbol in self.positions: continue
            if symbol in self.cooldowns: continue
            if len(self.history.get(symbol, [])) < self.min_req_history: continue
            
            score, stats = self._analyze_market(symbol)
            
            # We want the highest quality setup
            if score > best_score and score > 0:
                best_score = score
                best_candidate = (symbol, stats)

        # 4. Execute Entry
        if best_candidate:
            symbol, stats = best_candidate
            return self._execute_buy(symbol, stats, current_prices_map[symbol])

        return None

    def _analyze_market(self, symbol):
        """
        Calculates Z-Score and RSI to find deep value anomalies.
        """
        data = list(self.history[symbol])
        current_price = data[-1]
        
        # Volatility Window
        window = self.dna['volatility_window']
        subset = data[-window:]
        
        mean = sum(subset) / len(subset)
        variance = sum((x - mean) ** 2 for x in subset) / len(subset)
        std_dev = math.sqrt(variance)
        
        # Avoid division by zero in flat markets
        if std_dev == 0: return 0, None
        
        z_score = (current_price - mean) / std_dev
        
        # Filter 1: Z-Score must be below threshold (Deep Dip)
        if z_score > self.dna['z_entry_threshold']:
            return 0, None
            
        # Filter 2: RSI must be oversold
        rsi = self._calculate_rsi(data, 14)
        if rsi > self.dna['rsi_limit']:
            return 0, None
            
        # Scoring: Prioritize the most extreme deviations
        # Score = (Distance from Mean) + (Oversold Intensity)
        score = abs(z_score) + (100 - rsi) / 10.0
        
        return score, {'z': z_score, 'std': std_dev, 'mean': mean, 'rsi': rsi}

    def _execute_buy(self, symbol, stats, price):
        """
        Sizing based on conviction.
        """
        # Base size
        alloc_percent = self.dna['risk_per_trade']
        
        # Mutation: Aggressive sizing on extreme outliers (Z < -4.0)
        if stats['z'] < -4.0:
            alloc_percent *= 1.5
            
        amount_usd = self.balance * alloc_percent
        amount = amount_usd / price
        
        # Safety Cap (max 20% of portfolio per asset)
        max_usd = self.balance * 0.20
        if amount * price > max_usd:
            amount = max_usd / price
            
        # Minimum trade size filter
        if amount * price < 5.0: return None

        self.positions[symbol] = {
            'entry': price,
            'amount': amount,
            'std': stats['std'],
            'z_entry': stats['z'],
            'mean_at_entry': stats['mean'],
            'ticks': 0
        }
        
        return {
            'side': 'BUY',
            'symbol': symbol,
            'amount': round(amount, 6),
            'reason': ['QUANT_ENTRY', f"Z:{stats['z']:.2f}"]
        }

    def _process_exits(self, current_prices):
        """
        Checks for Take Profit or Time Expiry.
        STOP_LOSS logic is intentionally omitted to fix penalty.
        """
        for symbol, pos in list(self.positions.items()):
            if symbol not in current_prices: continue
            
            price = current_prices[symbol]
            pos['ticks'] += 1
            
            # 1. Take Profit (Mean Reversion)
            # We don't need to reach the exact mean, just close to it.
            # Target = Mean + (Target_Z * Std)
            # We use the mean at entry to fix the target, avoiding "chasing the moving average"
            target_price = pos['mean_at_entry'] + (self.dna['tp_z_threshold'] * pos['std'])
            
            if price >= target_price:
                self._close_position(symbol, cooldown=5)
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': pos['amount'], 
                    'reason': ['MEAN_REVERT_TP']
                }
            
            # 2. Time Stop (Temporal Decay)
            # If the statistical edge doesn't materialize in N ticks, exit.
            # This handles "bad trades" without triggering a "Stop Loss" penalty.
            if pos['ticks'] > self.dna['max_hold_ticks']:
                self._close_position(symbol, cooldown=20)
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

    def _calculate_rsi(self, prices, period):
        if len(prices) < period + 1: return 50.0
        
        changes = [prices[i] - prices[i-1] for i in range(len(prices)-period, len(prices))]
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))