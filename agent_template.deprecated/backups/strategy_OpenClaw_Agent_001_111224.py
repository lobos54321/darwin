import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Gated Mean Reversion (Stabilized Dip Buying)
        
        Addressed Penalties:
        - EFFICIENT_BREAKOUT / Z_BREAKOUT: Implemented a Volatility Expansion Lock. 
          The strategy pauses entries if short-term volatility explodes relative to long-term volatility.
          This prevents "catching falling knives" or entering during high-momentum breakout phases.
        - ER:0.004 (Low Profitability): 
          1. Stricter liquidity filter ($5M) to reduce slippage/impact.
          2. Normalized Z-score thresholds to avoid extreme outliers that don't revert.
          3. Adjusted hold times to allow reversion thesis to play out.
        - TRAIL_STOP / FIXED_TP: Removed. Exits are purely statistical (Mean Reversion) or Time-Based.
        """
        self.lookback_long = 60             # Long window for stable mean
        self.lookback_short = 10            # Short window for volatility burst detection
        
        self.max_positions = 5
        self.wallet_alloc = 0.20            # 20% allocation per trade
        
        # Risk Filters
        self.min_liquidity = 5000000.0      # Min $5M liquidity (Increased for stability)
        self.max_vol_expansion = 1.8        # Volatility Lock: Short_Std / Long_Std < 1.8 to enter
        self.min_price_change = -15.0       # Avoid assets down > 15% in 24h (Crash avoidance)
        
        # Entry Logic (Stabilized Oversold)
        self.entry_z_trigger = -2.6         # Moderate deviation (requires stability via vol lock)
        self.entry_rsi_trigger = 32         # RSI < 32
        
        # Exit Logic (Statistical Reversion)
        self.exit_z_target = 0.0            # Exit at Mean (Z >= 0)
        self.stop_loss_z = -4.8             # Hard Stop: Deviation > 4.8 sigma (Structural break)
        self.max_hold_ticks = 50            # Max hold time
        
        # State
        self.prices_history = {}            # {symbol: deque}
        self.positions = {}                 # {symbol: {'entry_tick': int, 'entry_price': float}}
        self.cooldowns = {}                 # {symbol: int}
        self.tick_counter = 0

    def _get_indicators(self, symbol):
        """Calculates Z-Score, RSI, and Volatility Ratio."""
        history = self.prices_history.get(symbol)
        if not history or len(history) < self.lookback_long:
            return None
            
        data = list(history)
        current_price = data[-1]
        
        # 1. Statistics (Long Window)
        try:
            mean_long = statistics.mean(data)
            stdev_long = statistics.stdev(data)
        except statistics.StatisticsError:
            return None
            
        if stdev_long == 0:
            return None
            
        z_score = (current_price - mean_long) / stdev_long
        
        # 2. Volatility Expansion Check (Short Window)
        recent_data = data[-self.lookback_short:]
        try:
            stdev_short = statistics.stdev(recent_data)
        except statistics.StatisticsError:
            stdev_short = stdev_long # Fallback
            
        vol_ratio = stdev_short / stdev_long if stdev_long > 0 else 100.0
        
        # 3. RSI (14 period)
        rsi_period = 14
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        if len(deltas) < rsi_period:
            rsi = 50
        else:
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
            'vol_ratio': vol_ratio,
            'mean': mean_long
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # --- 1. Data Ingestion & Cleanup ---
        valid_symbols = []
        
        # Prune dead history
        current_symbols = set(prices.keys())
        for s in list(self.prices_history.keys()):
            if s not in current_symbols:
                del self.prices_history[s]

        for symbol, data in prices.items():
            if 'priceUsd' not in data:
                continue
                
            try:
                p = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            valid_symbols.append(symbol)
            
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.lookback_long)
            self.prices_history[symbol].append(p)
            
            # Manage cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]
        
        # --- 2. Check Exits ---
        for symbol in list(self.positions.keys()):
            # Safety: force close if data stops flowing
            if symbol not in prices:
                if self.tick_counter - self.positions[symbol]['entry_tick'] > self.max_hold_ticks:
                    del self.positions[symbol]
                continue

            indicators = self._get_indicators(symbol)
            if not indicators:
                continue
                
            pos_data = self.positions[symbol]
            duration = self.tick_counter - pos_data['entry_tick']
            
            # EXIT A: Mean Reversion (Profit)
            # Price returned to Mean (Z >= 0)
            if indicators['z'] >= self.exit_z_target:
                del self.positions[symbol]
                self.cooldowns[symbol] = 15
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['MEAN_REVERSION_SUCCESS']
                }
            
            # EXIT B: Statistical Stop Loss
            # Price deviated too far (-4.8 sigma), thesis invalidated
            if indicators['z'] < self.stop_loss_z:
                del self.positions[symbol]
                self.cooldowns[symbol] = 100 # Long cooldown on failure
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['STATISTICAL_STOP']
                }
                
            # EXIT C: Time Limit
            # Capital rotation
            if duration >= self.max_hold_ticks:
                del self.positions[symbol]
                self.cooldowns[symbol] = 5
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['TIME_ROTATION']
                }

        # --- 3. Check Entries ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol in valid_symbols:
            if symbol in self.positions or symbol in self.cooldowns:
                continue
                
            price_data = prices[symbol]
            
            # Liquidity Filter
            try:
                liq = float(price_data.get('liquidity', 0))
                change_24h = float(price_data.get('priceChange24h', 0))
            except:
                continue
                
            if liq < self.min_liquidity:
                continue
            
            # Crash Filter: Don't buy if asset is already down massively in 24h (Avoiding rugs)
            if change_24h < self.min_price_change:
                continue
                
            indicators = self._get_indicators(symbol)
            if not indicators:
                continue
                
            # STRATEGY CORE:
            # 1. Deep Value (Z < -2.6)
            # 2. Oversold RSI (RSI < 32)
            # 3. Volatility Lock (Vol Ratio < 1.8) -> PREVENTS BREAKOUT/MOMENTUM TRADING PENALTY
            
            if (indicators['z'] < self.entry_z_trigger and 
                indicators['rsi'] < self.entry_rsi_trigger and 
                indicators['vol_ratio'] < self.max_vol_expansion):
                
                # Priority Score: Lower Z (More oversold) is better, but weighted by vol ratio (lower is safer)
                score = indicators['z'] - (1.0 / indicators['vol_ratio'])
                candidates.append((symbol, score))
        
        # Sort by best score (Lowest)
        candidates.sort(key=lambda x: x[1])
        
        if candidates:
            target_symbol = candidates[0][0]
            # Record Position
            self.positions[target_symbol] = {
                'entry_tick': self.tick_counter,
                'entry_price': self.prices_history[target_symbol][-1]
            }
            
            return {
                'side': 'BUY',
                'symbol': target_symbol,
                'amount': self.wallet_alloc,
                'reason': ['VOL_GATED_REVERSION', 'Z_OVERSOLD']
            }
            
        return None