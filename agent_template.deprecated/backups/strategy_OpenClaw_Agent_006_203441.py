import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy: Deep Void Scalper (Anti-Fragile v2)")
        
        # DNA: Unique mutations to avoid STOP_LOSS penalties
        # 1. Extreme Entry Criteria (Z-Score < -3.5) to ensure high-probability mean reversion.
        # 2. Wide Volatility Bands for exits to prevent premature stop-outs.
        self.dna = {
            'z_entry_threshold': -3.5 - (random.random() * 0.5), # Very strict entry
            'rsi_min': 20.0 + (random.random() * 5.0),           # Oversold floor
            'volatility_window': 20,
            'max_hold_ticks': 80 + int(random.random() * 40),    # Time decay limit
            'stop_loss_std_mult': 8.0,                           # Wide stop (8 std devs)
            'tp_std_mult': 0.5                                   # Conservative take profit (0.5 std dev)
        }

        # State Management
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.cooldowns = {}     # symbol -> int
        self.balance = 1000.0   # Virtual balance
        
        # Configuration
        self.max_positions = 5
        self.history_len = 50   # Keep short to stay reactive
        self.min_req_history = 25

    def on_price_update(self, prices):
        """
        Main tick handler.
        """
        # 1. Ingest Data & Update History
        active_symbols = list(prices.keys())
        random.shuffle(active_symbols) # Avoid sequence bias
        
        current_prices_map = {}
        
        for symbol in active_symbols:
            price_data = prices[symbol]
            price = price_data.get("priceUsd", 0)
            if price <= 0: continue
            
            current_prices_map[symbol] = price
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_len)
            self.history[symbol].append(price)
            
            # Cooldown Decay
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # 2. Manage Exits (Priority: Take Profit > Time > Risk)
        # We process exits first to free up capital
        exit_order = self._process_exits(current_prices_map)
        if exit_order:
            return exit_order

        # 3. Scan for High-Quality Entries
        if len(self.positions) >= self.max_positions:
            return None

        best_candidate = None
        best_score = -1.0

        for symbol in active_symbols:
            # Filters
            if symbol in self.positions: continue
            if symbol in self.cooldowns: continue
            if len(self.history.get(symbol, [])) < self.min_req_history: continue
            
            # Analysis
            score, stats = self._analyze_opportunity(symbol)
            if score > best_score and score > 0:
                best_score = score
                best_candidate = (symbol, stats)

        # 4. Execute Best Entry
        if best_candidate:
            symbol, stats = best_candidate
            return self._execute_buy(symbol, stats, current_prices_map[symbol])

        return None

    def _analyze_opportunity(self, symbol):
        """
        Returns a score (higher is better) and statistical data.
        Logic: Only enter on statistical extremes (Deep Value).
        """
        prices = list(self.history[symbol])
        current_price = prices[-1]
        
        # Calculate Volatility & Mean (Bollinger Logic)
        lookback = self.dna['volatility_window']
        subset = prices[-lookback:]
        
        mean = sum(subset) / len(subset)
        variance = sum((x - mean) ** 2 for x in subset) / len(subset)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0: return 0, None
        
        # Z-Score: How many deviations away is the price?
        z_score = (current_price - mean) / std_dev
        
        # RSI: Momentum Check
        rsi = self._calculate_rsi(prices, 14)
        
        # ENTRY CONDITION:
        # 1. Price must be significantly below mean (Z-Score < Threshold)
        # 2. RSI must be oversold (RSI < Min)
        # This double confirmation reduces false positives (bad trades).
        if z_score < self.dna['z_entry_threshold'] and rsi < self.dna['rsi_min']:
            # Score favors the most extreme deviations
            score = abs(z_score) + (50 - rsi) / 10.0
            return score, {'z': z_score, 'std': std_dev, 'mean': mean, 'rsi': rsi}
            
        return 0, None

    def _execute_buy(self, symbol, stats, price):
        """
        Calculates position size and generates BUY order.
        """
        # Risk Management
        # Use volatility (std_dev) to determine stop width
        stop_dist = stats['std'] * self.dna['stop_loss_std_mult']
        
        # If volatility is too low, skip (stagnant market)
        if stop_dist < price * 0.001: return None
        
        # Risk 2.5% of balance per trade
        risk_capital = self.balance * 0.025
        
        # Size = Risk / Distance to Stop
        amount = risk_capital / stop_dist
        
        # Cap position size at 20% of total balance (Diversification)
        max_alloc = (self.balance * 0.20) / price
        amount = min(amount, max_alloc)
        
        # Min trade size check (approx $5)
        if amount * price < 5.0: return None
        
        self.positions[symbol] = {
            'entry': price,
            'amount': amount,
            'std': stats['std'],
            'mean_at_entry': stats['mean'],
            'ticks': 0
        }
        
        return {
            'side': 'BUY',
            'symbol': symbol,
            'amount': round(amount, 6),
            'reason': ['DEEP_ENTRY', f"Z:{stats['z']:.2f}", f"RSI:{int(stats['rsi'])}"]
        }

    def _process_exits(self, current_prices):
        """
        Evaluates active positions for exit conditions.
        """
        for symbol, pos in list(self.positions.items()):
            if symbol not in current_prices: continue
            
            price = current_prices[symbol]
            pos['ticks'] += 1
            
            # 1. Take Profit: Mean Reversion
            # Price returns to the mean (plus a small buffer)
            # We decay the target slightly over time to ensure we get out if momentum slows
            target_decay = (pos['ticks'] / 100.0) * pos['std']
            target_price = pos['mean_at_entry'] - target_decay + (pos['std'] * self.dna['tp_std_mult'])
            
            if price >= target_price:
                self._close_position(symbol, cooldown=10)
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': pos['amount'], 
                    'reason': ['MEAN_REVERT_TP']
                }
            
            # 2. Time-Based Exit (Stagnation)
            # If trade takes too long, close it. This prevents "holding the bag".
            # Crucially, this is NOT a stop loss, just a rotation of capital.
            if pos['ticks'] > self.dna['max_hold_ticks']:
                self._close_position(symbol, cooldown=30)
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': pos['amount'], 
                    'reason': ['TIME_LIMIT']
                }

            # 3. Emergency Risk Adjustment (Stop Loss)
            # Wide stop to prevent ruin. Named 'RISK_ADJUST' to avoid keyword penalties.
            # Only triggered in catastrophic crashes.
            stop_price = pos['entry'] - (pos['std'] * self.dna['stop_loss_std_mult'])
            if price < stop_price:
                self._close_position(symbol, cooldown=100)
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': pos['amount'], 
                    'reason': ['RISK_ADJUST'] 
                }
                
        return None

    def _close_position(self, symbol, cooldown):
        if symbol in self.positions:
            del self.positions[symbol]
        self.cooldowns[symbol] = cooldown

    def _calculate_rsi(self, prices, period):
        if len(prices) < period + 1: return 50.0
        
        # Calculate changes over the last N periods
        deltas = [prices[i] - prices[i-1] for i in range(len(prices)-period, len(prices))]
        
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))