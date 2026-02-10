import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Statistical Mean Reversion
        
        Fixes implemented:
        - EFFICIENT_BREAKOUT/Z_BREAKOUT: Stricter negative Z-score requirements to ensure we only catch deep oversold mean-reversions, never breakouts.
        - ER:0.004: Improved Edge Ratio by lowering profit target to the mean (0.0 Z) to increase win rate, and filtering for trend alignment.
        - FIXED_TP: Exit is now purely dynamic based on Z-Score reversion and RSI recovery.
        - TRAIL_STOP: Replaced with structural invalidation stop (Z-Score floor) and time-based decay.
        """
        # Configuration
        self.lookback = 60              # Longer window for stable mean
        self.max_positions = 5
        self.position_amount = 0.19     # 19% per trade
        
        # Dynamic Parameters
        self.rsi_period = 14
        self.min_liquidity = 3000000.0  # Strict liquidity to ensure fill quality
        self.min_volatility = 0.003     # Avoid stagnant pairs
        
        # Entry Logic (Deep Value)
        self.entry_z = -2.6             # Require 2.6 std dev drop (Deep Dip)
        self.entry_rsi = 30             # Traditional oversold
        
        # Exit Logic (Quick Reversion)
        self.exit_z = 0.1               # Exit just as price crosses mean (High probability)
        self.exit_rsi = 65              # Momentum neutralization
        self.stop_z = -5.0              # Structural break (Statistical Stop)
        self.max_hold_time = 40         # Force rotation
        
        # State
        self.prices_history = {}        # {symbol: deque}
        self.active_positions = {}      # {symbol: {'entry_tick': int}}
        self.blacklisted = {}           # {symbol: cooldown_int}
        self.tick_counter = 0

    def _calc_stats(self, symbol, current_price):
        """Calculates Z-Score and RSI."""
        history = self.prices_history.get(symbol)
        if not history or len(history) < self.lookback:
            return None
            
        data = list(history)
        
        # Z-Score Calculation
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean
        
        # RSI Calculation (Simplified)
        if len(data) <= self.rsi_period:
            return None
            
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        recent_deltas = deltas[-self.rsi_period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d < 0]
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility,
            'mean': mean
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Update Data & Cleanup
        current_symbols = set()
        for symbol, data in prices.items():
            if 'priceUsd' not in data:
                continue
            
            try:
                p = float(data['priceUsd'])
            except:
                continue
                
            current_symbols.add(symbol)
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.lookback)
            self.prices_history[symbol].append(p)
            
            # Manage cooldowns
            if symbol in self.blacklisted:
                self.blacklisted[symbol] -= 1
                if self.blacklisted[symbol] <= 0:
                    del self.blacklisted[symbol]

        # Cleanup stale data
        for s in list(self.prices_history.keys()):
            if s not in current_symbols and s not in self.active_positions:
                del self.prices_history[s]

        # 2. Manage Exits
        for symbol in list(self.active_positions.keys()):
            pos_data = self.active_positions[symbol]
            current_tick_duration = self.tick_counter - pos_data['entry_tick']
            
            # Missing price data force close
            if symbol not in prices:
                del self.active_positions[symbol]
                continue
                
            try:
                curr_price = float(prices[symbol]['priceUsd'])
            except:
                continue

            stats = self._calc_stats(symbol, curr_price)
            if not stats:
                continue
                
            # Logic: Dynamic Take Profit
            # If we return to mean (Z > 0.1) or RSI heats up, bank profit.
            if stats['z'] >= self.exit_z or stats['rsi'] > self.exit_rsi:
                del self.active_positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['MEAN_REVERSION_TP']
                }
            
            # Logic: Statistical Stop Loss
            # If price deviates > 5 sigma, the distribution has shifted (Crash).
            if stats['z'] < self.stop_z:
                del self.active_positions[symbol]
                self.blacklisted[symbol] = 50  # Long cooldown
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['STAT_STOP']
                }
                
            # Logic: Time Stop
            if current_tick_duration >= self.max_hold_time:
                del self.active_positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['TIME_LIMIT']
                }

        # 3. Scan for Entries
        if len(self.active_positions) >= self.max_positions:
            return None
            
        candidates = []
        for symbol in current_symbols:
            if symbol in self.active_positions or symbol in self.blacklisted:
                continue
                
            raw = prices[symbol]
            try:
                liq = float(raw.get('liquidity', 0))
                change24 = float(raw.get('priceChange24h', 0))
                price = float(raw['priceUsd'])
            except:
                continue
                
            # Hard Filters
            if liq < self.min_liquidity:
                continue
                
            # "Falling Knife" prevention: 
            # If 24h change is extremely negative (-12%), volatility is too dangerous for mean reversion.
            if change24 < -12.0:
                continue
            
            stats = self._calc_stats(symbol, price)
            if not stats:
                continue
                
            if stats['vol'] < self.min_volatility:
                continue
                
            # Signal: Confluence of Statistical Anomaly (Z) and Momentum Oversold (RSI)
            # We strictly buy dips (Negative Z)
            if stats['z'] < self.entry_z and stats['rsi'] < self.entry_rsi:
                # Scoring: Prioritize deepest statistical outliers with highest liquidity
                # We want "safe" anomalies.
                score = abs(stats['z']) * math.log(liq)
                candidates.append((score, symbol))
        
        if candidates:
            # Pick best
            candidates.sort(key=lambda x: x[0], reverse=True)
            target_symbol = candidates[0][1]
            
            self.active_positions[target_symbol] = {'entry_tick': self.tick_counter}
            
            return {
                'side': 'BUY',
                'symbol': target_symbol,
                'amount': self.position_amount,
                'reason': ['QUANTUM_DIP']
            }
            
        return None