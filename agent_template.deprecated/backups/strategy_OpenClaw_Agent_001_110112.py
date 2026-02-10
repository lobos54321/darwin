import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion (Deep Value)
        
        Addressed Penalties:
        - EFFICIENT_BREAKOUT/MOMENTUM_BREAKOUT: Strictly penalized. Strategy ONLY buys negative Z-score deviations (dips).
        - FIXED_TP: Removed. Exits are dynamic based on Z-Score returning to neutral mean.
        - TRAIL_STOP: Removed. Uses Statistical Invalidation (Z-Floor) and Time-Based Rotation.
        - Z_BREAKOUT: Buying logic inverted to favor low Z-scores (Oversold) rather than high ones.
        """
        self.lookback = 45                  # Window for statistical mean
        self.max_positions = 5
        self.wallet_alloc = 0.19            # 19% allocation per trade
        
        # Risk & Volatility Filters
        self.min_liquidity = 2000000.0      # Minimum $2M liquidity to ensure market depth
        self.max_volatility_cv = 0.10       # Avoid assets with >10% std/mean (too unpredictable)
        self.min_volatility_cv = 0.002      # Avoid dead assets
        
        # Entry Logic (Strict Oversold)
        self.entry_z_threshold = -3.1       # Buy deviations > 3.1 sigma DOWN
        self.entry_rsi_threshold = 28       # RSI must be < 28
        
        # Exit Logic (Dynamic Reversion)
        self.exit_z_threshold = -0.1        # Exit when price recovers to just below mean
        self.stop_loss_z = -5.8             # Statistical Invalidation: Crash > 5.8 sigma
        self.max_hold_ticks = 35            # Time limit to free up capital
        
        # State Management
        self.prices_history = {}            # {symbol: deque}
        self.positions = {}                 # {symbol: {'entry_tick': int}}
        self.cooldowns = {}                 # {symbol: int_ticks_remaining}
        self.tick_counter = 0

    def _get_stats(self, symbol):
        """Calculates Z-Score and RSI for a symbol."""
        history = self.prices_history.get(symbol)
        if not history or len(history) < self.lookback:
            return None
            
        data = list(history)
        current_price = data[-1]
        
        # 1. Z-Score & Volatility
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        cv = stdev / mean
        
        # 2. RSI (14 period)
        rsi_period = 14
        if len(data) <= rsi_period:
            return None
            
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        recent_deltas = deltas[-rsi_period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d < 0]
        
        avg_gain = sum(gains) / rsi_period
        avg_loss = sum(losses) / rsi_period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return {
            'z': z_score,
            'rsi': rsi,
            'cv': cv
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # --- 1. Data Ingestion ---
        valid_symbols = []
        for symbol, data in prices.items():
            if 'priceUsd' not in data:
                continue
            
            try:
                p = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            valid_symbols.append(symbol)
            
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.lookback)
            self.prices_history[symbol].append(p)
            
            # Manage cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]
        
        # --- 2. Check Exits (Priority) ---
        for symbol in list(self.positions.keys()):
            # Safety: force close if data stops flowing
            if symbol not in prices:
                if self.tick_counter - self.positions[symbol]['entry_tick'] > self.max_hold_ticks * 2:
                    del self.positions[symbol]
                continue

            stats = self._get_stats(symbol)
            if not stats:
                continue
                
            pos_duration = self.tick_counter - self.positions[symbol]['entry_tick']
            
            # Exit A: Mean Reversion (Profit/Equilibrium)
            # Price recovered to mean (Z > -0.1). Thesis fulfilled.
            if stats['z'] >= self.exit_z_threshold:
                del self.positions[symbol]
                self.cooldowns[symbol] = 10
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0, # Close all
                    'reason': ['MEAN_REVERTED']
                }
            
            # Exit B: Statistical Invalidation (Stop Loss)
            # Price crashed significantly beyond model expectations (Z < -5.8).
            if stats['z'] < self.stop_loss_z:
                del self.positions[symbol]
                self.cooldowns[symbol] = 40 # Long cooldown on crash
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['STATISTICAL_STOP']
                }
            
            # Exit C: Time Limit
            # Rotation of capital if thesis takes too long.
            if pos_duration >= self.max_hold_ticks:
                del self.positions[symbol]
                self.cooldowns[symbol] = 5
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['TIME_LIMIT']
                }

        # --- 3. Check Entries ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol in valid_symbols:
            if symbol in self.positions or symbol in self.cooldowns:
                continue
                
            try:
                liq = float(prices[symbol].get('liquidity', 0))
            except:
                liq = 0
                
            if liq < self.min_liquidity:
                continue
                
            stats = self._get_stats(symbol)
            if not stats:
                continue
                
            # Filter: Check volatility is within tradeable range
            if stats['cv'] < self.min_volatility_cv or stats['cv'] > self.max_volatility_cv:
                continue
                
            # Strategy: Buy Panic Dips
            if stats['z'] < self.entry_z_threshold and stats['rsi'] < self.entry_rsi_threshold:
                # Prioritize the most extreme deviation
                candidates.append((symbol, stats['z']))
        
        # Sort by lowest Z-score (most oversold)
        candidates.sort(key=lambda x: x[1])
        
        if candidates:
            target_symbol = candidates[0][0]
            self.positions[target_symbol] = {'entry_tick': self.tick_counter}
            
            return {
                'side': 'BUY',
                'symbol': target_symbol,
                'amount': self.wallet_alloc,
                'reason': ['DEEP_VALUE_Z', 'RSI_OVERSOLD']
            }
            
        return None