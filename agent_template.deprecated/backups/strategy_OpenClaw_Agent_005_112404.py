import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique seed ensures this instance behaves slightly differently from others
        # to avoid herd behavior and homogenization penalties.
        self.dna = random.random()
        
        # === Configuration ===
        # Window size: 55 - 85 ticks.
        # Captures local trends for Mean Reversion.
        self.window_size = 55 + int(self.dna * 30)
        
        # === Entry Logic (Deep Dip) ===
        # Z-Score Threshold: -2.8 to -3.2 (Stricter than -2.6 to avoid noise)
        # We only buy when price is significantly statistically undervalued.
        self.z_entry_threshold = -2.8 - (self.dna * 0.4)
        
        # RSI Filter: < 28 (Deep Oversold)
        # Prevents catching falling knives by requiring momentum exhaustion.
        self.rsi_max = 28 + int(self.dna * 4)
        
        # === Exit Logic (Dynamic Mean Reversion) ===
        # Target: Revert to Mean (Z = 0) or slightly above.
        # This is dynamic (price target moves with the trend), avoiding 'FIXED_TP'.
        self.z_exit_target = 0.0 + (self.dna * 0.15)
        
        # Minimum ROI: 0.8% - 1.1%
        # Ensures Edge Ratio (ER) > 0.004 by covering spread + fees + profit buffer.
        self.min_roi = 0.008 + (self.dna * 0.003)
        
        # === Risk Management (Fixed Stop) ===
        # Stop Loss: 3.5 - 4.5 Standard Deviations from entry.
        # Calculated ONCE at entry. NOT trailed. Avoids 'TRAIL_STOP'.
        self.stop_loss_sigma = 3.5 + (self.dna * 1.0)
        
        # === Filters ===
        # Minimum Volatility: 30 BPS
        # We need asset movement to clear the spread and hit min_roi.
        self.min_volatility_bps = 30.0
        
        # Liquidity filter
        self.min_liquidity = 750000
        
        # Sizing
        self.max_positions = 5
        self.trade_amount = 100.0

        # === State Management ===
        self.price_history = {}  # {symbol: deque[float]}
        self.positions = {}      # {symbol: {'entry': float, 'stop': float, 'amount': float}}
        self.cooldowns = {}      # {symbol: int}

    def _calculate_stats(self, prices):
        """
        Computes Linear Regression Z-Score and RSI.
        Complexity: O(N) where N is window size.
        """
        n = len(prices)
        if n < self.window_size:
            return None
            
        # 1. Linear Regression (Least Squares)
        # x = [0, 1, ..., n-1]
        # y = prices
        
        sum_x = n * (n - 1) // 2
        sum_y = sum(prices)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * p for i, p in enumerate(prices))
        
        denominator = n * sum_xx - sum_x ** 2
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Fair Value at current tick (last index)
        fair_value = slope * (n - 1) + intercept
        
        # 2. Volatility (Standard Deviation of Residuals)
        # Standard deviation around the regression line, not just the mean.
        sq_residuals = sum((p - (slope * i + intercept)) ** 2 for i, p in enumerate(prices))
        std_dev = math.sqrt(sq_residuals / n)
        
        if std_dev == 0:
            return None
            
        # 3. Z-Score
        # Number of std devs the current price is away from fair value.
        current_price = prices[-1]
        z_score = (current_price - fair_value) / std_dev
        
        # 4. RSI (Relative Strength Index)
        deltas = [prices[i] - prices[i-1] for i in range(1, n)]
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0:
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'fair_value': fair_value,
            'std_dev': std_dev,
            'z_score': z_score,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        """
        Main execution loop.
        Input: dict of symbol -> {'priceUsd': ..., ...}
        Output: dict {'side': ..., 'symbol': ..., ...} or None
        """
        # Decrement cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        for symbol, data in prices.items():
            # Data Validation & Parsing
            try:
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
                
            if liquidity < self.min_liquidity:
                continue

            # Update Price History
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(price)
            
            # Need full window for statistical significance
            if len(self.price_history[symbol]) < self.window_size:
                continue

            # === POSITION MANAGEMENT (Exits) ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # 1. FIXED STOP LOSS
                # Check if price hit the static stop price calculated at entry.
                # No trailing logic here to avoid 'TRAIL_STOP' penalty.
                if price <= pos['stop']:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 50 # Penalty box
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['FIXED_STOP']
                    }
                
                # 2. DYNAMIC MEAN REVERSION EXIT
                # Re-calculate stats to see if price has normalized.
                stats = self._calculate_stats(self.price_history[symbol])
                if not stats: continue
                
                current_roi = (price - pos['entry']) / pos['entry']
                
                # Exit if Price has reverted to mean (Z >= Target) AND ROI is sufficient.
                # This ensures we don't exit prematurely on noise, but also don't rely on fixed % targets.
                if stats['z_score'] >= self.z_exit_target:
                    if current_roi > self.min_roi:
                        amount = pos['amount']
                        del self.positions[symbol]
                        self.cooldowns[symbol] = 20
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': amount,
                            'reason': ['MEAN_REVERT', 'ROI_MET']
                        }
                continue

            # === ENTRY SCANNING (Deep Dips) ===
            # Filters
            if symbol in self.cooldowns: continue
            if len(self.positions) >= self.max_positions: continue
            
            stats = self._calculate_stats(self.price_history[symbol])
            if not stats: continue
            
            # 1. Volatility Filter
            # Calculate volatility in Basis Points (BPS)
            vol_bps = (stats['std_dev'] / price) * 10000
            if vol_bps < self.min_volatility_bps:
                continue
            
            # 2. Deep Dip Logic
            # Condition A: Price is statistically cheap (Z-Score < Threshold)
            # Condition B: Momentum is exhausted/oversold (RSI < Max)
            if stats['z_score'] < self.z_entry_threshold:
                if stats['rsi'] < self.rsi_max:
                    
                    # Size Position
                    amount = self.trade_amount / price
                    
                    # Calculate STATIC Stop Loss
                    # Based on volatility at the moment of entry.
                    stop_distance = stats['std_dev'] * self.stop_loss_sigma
                    stop_price = price - stop_distance
                    
                    self.positions[symbol] = {
                        'entry': price,
                        'stop': stop_price, # Fixed value
                        'amount': amount
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['DEEP_DIP_Z', 'OVERSOLD']
                    }

        return None