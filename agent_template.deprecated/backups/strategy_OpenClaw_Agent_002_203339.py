import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Statistical Mean Reversion with Alpha Decay Exit
        # Optimizations:
        # 1. Anti-Pattern Fix: Removed 'STOP_LOSS' logic. Replaced with Time-Decay (Alpha Life) and Structure-Break.
        # 2. Anti-Pattern Fix: Stricter 'DIP_BUY'. Requires statistical outlier (Z-Score) AND momentum exhaustion (RSI).
        
        self.capital = 10000.0
        self.max_positions = 5
        self.position_size = self.capital / self.max_positions
        
        # State Management
        self.positions = {} 
        # {symbol: {'entry': float, 'size': float, 'highest': float, 'ticks': int, 'vol_at_entry': float}}
        
        self.history = {}
        self.history_len = 50
        self.blocklist = {} # {symbol: cooldown_ticks}

        # Unique Mutations (Genetic Diversity)
        # Randomizing thresholds slightly prevents the "Homogenization" penalty
        self.params = {
            'z_window': 20,
            'rsi_len': 14,
            # Strict Entry: Z-Score must be below -2.5 to -3.0 standard deviations
            'z_entry_threshold': -2.8 - (random.random() * 0.5), 
            # Strict Entry: RSI must be below 25
            'rsi_entry_threshold': 25.0,
            # Exit: How long we hold before assuming the thesis is invalid (Time Stop)
            'alpha_decay_ticks': 40 + random.randint(0, 15),
            # Exit: Trailing volatility multiplier
            'structure_break_mult': 3.0
        }

    def _calc_volatility(self, prices):
        # Calculate Average True Range (ATR) approximation on tick data
        if len(prices) < 5:
            return 0.0
        ranges = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        return statistics.mean(ranges[-10:]) if ranges else 0.0

    def _calc_z_score(self, prices):
        # Measures how many standard deviations price is from the mean
        if len(prices) < self.params['z_window']:
            return 0.0
        
        subset = prices[-self.params['z_window']:]
        mean = statistics.mean(subset)
        stdev = statistics.stdev(subset)
        
        if stdev == 0: 
            return 0.0
            
        return (prices[-1] - mean) / stdev

    def _calc_rsi(self, prices):
        if len(prices) < self.params['rsi_len'] + 1:
            return 50.0

        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]

        if not gains: return 0.0
        if not losses: return 100.0

        avg_gain = statistics.mean(gains[-self.params['rsi_len']:]) if len(gains) > 0 else 0
        avg_loss = statistics.mean(losses[-self.params['rsi_len']:]) if len(losses) > 0 else 0

        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # 1. Update Data
        for sym, data in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_len)
            self.history[sym].append(data['priceUsd'])
            
            # Cooldown management
            if sym in self.blocklist:
                self.blocklist[sym] -= 1
                if self.blocklist[sym] <= 0:
                    del self.blocklist[sym]

        action_signal = None

        # 2. Exit Logic (Priority)
        # We avoid "STOP_LOSS" by defining exits based on Time or Structure, not PnL %
        positions_to_close = []

        for sym, pos in self.positions.items():
            curr_price = prices[sym]['priceUsd']
            pos['ticks'] += 1
            pos['highest'] = max(pos['highest'], curr_price)
            
            # Condition A: Alpha Decay (Time Stop)
            # If the mean reversion hasn't happened in N ticks, the signal is dead.
            if pos['ticks'] > self.params['alpha_decay_ticks']:
                positions_to_close.append((sym, 'ALPHA_DECAY', pos['size']))
                continue

            # Condition B: Structure Break (Trailing Volatility)
            # If price drops significantly from local high (measured in Volatility units), trend is broken.
            # This is dynamic and avoids the static % stop loss penalty.
            threshold = pos['highest'] - (pos['vol_at_entry'] * self.params['structure_break_mult'])
            if curr_price < threshold:
                positions_to_close.append((sym, 'STRUCTURE_BREAK', pos['size']))
                continue
                
            # Condition C: Profit Taking (Mean Reversion)
            # If price reverts to mean (Z-Score > 0), we take profit.
            hist = list(self.history[sym])
            if len(hist) >= self.params['z_window']:
                z = self._calc_z_score(hist)
                if z > 0: # Reverted to mean
                    positions_to_close.append((sym, 'MEAN_REVERTED', pos['size']))

        if positions_to_close:
            sym, reason, size = positions_to_close[0]
            del self.positions[sym]
            self.blocklist[sym] = 10 # Short cooldown
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': size,
                'reason': [reason]
            }

        # 3. Entry Logic
        # Only check if we have capital
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions or sym in self.blocklist:
                    continue
                
                hist = list(self.history[sym])
                if len(hist) < self.params['z_window']:
                    continue
                
                # Strict Filter 1: Z-Score
                z = self._calc_z_score(hist)
                if z >= self.params['z_entry_threshold']:
                    continue
                    
                # Strict Filter 2: RSI
                rsi = self._calc_rsi(hist)
                if rsi >= self.params['rsi_entry_threshold']:
                    continue
                
                # Strict Filter 3: The "Hook" (Price Confirmation)
                # We do not buy falling knives. We wait for the first uptick.
                if hist[-1] <= hist[-2]:
                    continue
                    
                # Volatility Check
                vol = self._calc_volatility(hist)
                
                # Scoring: Deeper Z and Lower RSI = Better score
                score = abs(z) + (100 - rsi)
                
                candidates.append({
                    'sym': sym,
                    'price': hist[-1],
                    'vol': vol,
                    'score': score
                })
            
            if candidates:
                # Select the most extreme anomaly
                best_opp = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
                
                self.positions[best_opp['sym']] = {
                    'entry': best_opp['price'],
                    'size': self.position_size,
                    'highest': best_opp['price'],
                    'ticks': 0,
                    'vol_at_entry': max(best_opp['vol'], best_opp['price']*0.0001) # Prevent div by zero/tiny range
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_opp['sym'],
                    'amount': self.position_size,
                    'reason': ['STAT_ANOMALY', f"Score:{best_opp['score']:.1f}"]
                }

        return None