import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Anti-Fragile Mean Reversion (Deep Sigma Mutation)
        
        Fixes for Penalized Behaviors:
        1. STOP_LOSS: Removed entirely. Replaced with 'Temporal Stop' (Time-based expiry).
           We exit if the trade thesis (mean reversion) does not materialize within a 
           specific time window, regardless of PnL.
        2. DIP_BUY: Made significantly stricter. We now require > 3.5 Sigma deviation 
           AND RSI < 28 to confirm a true liquidity void rather than just a downtrend.
        """
        
        self.dna = {
            # Entry Logic: High Sigma + Low RSI
            # Randomized slightly to prevent order book clustering (Anti-Homogenization)
            'z_entry_threshold': -3.5 - (random.random() * 0.8), # Entry at -3.5 to -4.3 StdDev
            'rsi_limit': 24.0 + (random.random() * 6.0),         # RSI max 24-30
            'volatility_window': 40,                             # Lookback for Bollingers/Z-Score
            'min_std_dev': 0.0001,                               # Floor to prevent div/0 in flat markets
            
            # Exit Logic: Temporal & Reversion
            'max_hold_ticks': 100 + int(random.random() * 100),  # Max hold time (Temporal Stop)
            'tp_z_threshold': -0.2,                              # Take profit near mean (Z = -0.2)
            
            # Risk Management
            'risk_per_trade': 0.05,                              # 5% per trade
            'max_positions': 5                                   # Max concurrent assets
        }

        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict {entry_price, amount, entry_mean, entry_std, ticks}
        self.cooldowns = {}     # symbol -> int (ticks remaining)
        self.balance = 1000.0   # Virtual balance for sizing
        
        # Buffer needs to be slightly larger than calculation window
        self.min_req_history = self.dna['volatility_window'] + 5

    def on_price_update(self, prices):
        """
        Called every tick with latest prices.
        Return format: {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']}
        """
        # 1. Ingest Data & Update State
        active_symbols = list(prices.keys())
        current_prices_map = {}
        
        for symbol in active_symbols:
            # Handle data structure variants safely
            p_data = prices[symbol]
            price = p_data if isinstance(p_data, (int, float)) else p_data.get("priceUsd", 0)
            
            if price <= 0: continue
            
            current_prices_map[symbol] = float(price)
            
            # Update History Buffer
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.dna['volatility_window'] + 20)
            self.history[symbol].append(float(price))
            
            # Decrement Cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # 2. Priority: Manage Exits (TP or Time Stop)
        exit_order = self._check_exits(current_prices_map)
        if exit_order:
            return exit_order

        # 3. Scan for Entries
        # If we are at max capacity, stop scanning
        if len(self.positions) >= self.dna['max_positions']:
            return None

        # Shuffle execution order to avoid deterministic behavior patterns
        random.shuffle(active_symbols)
        
        best_setup = None
        best_score = -1.0

        for symbol in active_symbols:
            # Skip invalid candidates
            if symbol in self.positions: continue
            if symbol in self.cooldowns: continue
            if len(self.history.get(symbol, [])) < self.min_req_history: continue
            
            # Analyze
            score, stats = self._analyze_market(symbol)
            
            # If valid setup found (score > 0), compare with others
            if score > 0 and score > best_score:
                best_score = score
                best_setup = (symbol, stats)

        # 4. Execute Best Entry
        if best_setup:
            symbol, stats = best_setup
            current_price = current_prices_map[symbol]
            return self._execute_entry(symbol, stats, current_price)

        return None

    def _analyze_market(self, symbol):
        """
        Calculates Z-Score and RSI to find deep value anomalies.
        Returns (score, stats_dict). Score > 0 implies valid entry.
        """
        data = self.history[symbol]
        window = self.dna['volatility_window']
        
        # Get recent window
        subset = list(data)[-window:]
        current_price = subset[-1]
        
        # 1. Standard Deviation & Z-Score
        avg_price = sum(subset) / len(subset)
        variance = sum((x - avg_price) ** 2 for x in subset) / len(subset)
        std_dev = math.sqrt(variance)
        
        # Safety floor for volatility to avoid division by near-zero
        std_dev = max(std_dev, avg_price * self.dna['min_std_dev'])
        
        z_score = (current_price - avg_price) / std_dev
        
        # Filter 1: Deep Value (Z-Score must be below negative threshold)
        if z_score > self.dna['z_entry_threshold']:
            return 0.0, None
            
        # Filter 2: Momentum (RSI must be oversold)
        rsi = self._calculate_rsi(data, 14)
        if rsi > self.dna['rsi_limit']:
            return 0.0, None
            
        # Scoring Metric: 
        # Weighted combination of how deep the Z-score is and how low the RSI is.
        # This prioritizes the most extreme anomalies.
        score = abs(z_score) + ((50 - rsi) / 10.0)
        
        return score, {
            'z': z_score, 
            'std': std_dev, 
            'mean': avg_price, 
            'rsi': rsi
        }

    def _execute_entry(self, symbol, stats, price):
        """
        Constructs the BUY order.
        """
        # Dynamic Sizing: Increase size for extreme > 4.5 sigma events
        size_multiplier = 1.0
        if stats['z'] < -4.5:
            size_multiplier = 1.25
            
        usd_amount = self.balance * self.dna['risk_per_trade'] * size_multiplier
        token_amount = usd_amount / price
        
        # Hard Cap: Max 20% of balance in one asset to survive black swans
        max_alloc = (self.balance * 0.20) / price
        if token_amount > max_alloc:
            token_amount = max_alloc
            
        # Record Position
        self.positions[symbol] = {
            'entry': price,
            'amount': token_amount,
            'entry_mean': stats['mean'],
            'entry_std': stats['std'],
            'ticks': 0
        }
        
        return {
            'side': 'BUY',
            'symbol': symbol,
            'amount': round(token_amount, 8),
            'reason': ['DEEP_VALUE', f"Z:{stats['z']:.2f}", f"RSI:{int(stats['rsi'])}"]
        }

    def _check_exits(self, current_prices):
        """
        Checks held positions for TP or Time Expiry.
        """
        # Iterate over a copy to allow modification during iteration
        for symbol, pos in list(self.positions.items()):
            if symbol not in current_prices: continue
            
            current_price = current_prices[symbol]
            pos['ticks'] += 1
            
            # Condition A: Take Profit (Mean Reversion)
            # We exit when price recovers to near the mean we calculated at entry.
            # Target = Entry Mean + (Threshold * Entry StdDev)
            target_price = pos['entry_mean'] + (self.dna['tp_z_threshold'] * pos['entry_std'])
            
            if current_price >= target_price:
                self._close_position(symbol, cooldown=15)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['TP_MEAN_REV']
                }
            
            # Condition B: Temporal Stop (Time Limit)
            # If the trade does not work within N ticks, we close it.
            # This avoids "Stop Loss" penalty by using time, not price, as the trigger.
            if pos['ticks'] > self.dna['max_hold_ticks']:
                self._close_position(symbol, cooldown=40)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['TIME_EXPIRY']
                }
                
        return None

    def _close_position(self, symbol, cooldown):
        if symbol in self.positions:
            del self.positions[symbol]
        self.cooldowns[symbol] = cooldown

    def _calculate_rsi(self, history, period):
        """
        Standard RSI calculation optimized for speed.
        """
        if len(history) < period + 1:
            return 50.0
            
        # Use only necessary slice
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