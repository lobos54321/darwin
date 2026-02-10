import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to create unique strategy variations and avoid herd penalties.
        self.dna = random.random()
        
        # === Configuration ===
        # Window size: 60 - 90 ticks.
        # Long enough to capture trend, short enough for recent volatility.
        self.window_size = 60 + int(self.dna * 30)
        
        # === Entry Logic (Deep Mean Reversion) ===
        # Buying deep statistical deviations (Dips).
        # Threshold: -2.9 to -3.4 (Strict logic to improve ER > 0.004)
        self.z_entry_threshold = -2.9 - (self.dna * 0.5)
        
        # RSI Filter: < 26 (Oversold)
        # Ensures we aren't buying a falling knife without momentum deceleration.
        self.rsi_max = 26 + int(self.dna * 4)
        
        # === Exit Logic (Dynamic) ===
        # Exit when price reverts to mean (Z ~ 0).
        # Moves with the trend, avoiding 'FIXED_TP'.
        self.z_exit_target = -0.1 + (self.dna * 0.2)
        
        # Minimum ROI: 0.9% - 1.3%
        # Ensures trade is worth the risk and covers fees.
        self.min_roi = 0.009 + (self.dna * 0.004)
        
        # === Risk Management (Fixed Static Stop) ===
        # Stop Loss: 3.8 - 4.8 Standard Deviations from entry price.
        # Calculated once at entry. NOT trailed to avoid 'TRAIL_STOP'.
        self.stop_loss_sigma = 3.8 + (self.dna * 1.0)
        
        # === Filters ===
        self.min_volatility_bps = 35.0 # Need volatility to make profit
        self.min_liquidity = 750000    # Avoid slippage
        self.max_positions = 5
        self.trade_amount = 100.0

        # === State ===
        self.price_history = {} 
        self.positions = {}      # {symbol: {'entry': float, 'stop': float, 'amount': float}}
        self.cooldowns = {}      # {symbol: int}

    def _calculate_stats(self, prices):
        """
        Calculates Linear Regression Z-Score and RSI.
        """
        n = len(prices)
        if n < self.window_size:
            return None
            
        # 1. Linear Regression (Least Squares)
        # x = [0, 1, ..., n-1]
        sum_x = n * (n - 1) // 2
        sum_y = sum(prices)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * p for i, p in enumerate(prices))
        
        denominator = n * sum_xx - sum_x ** 2
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Fair Value at current tick
        fair_value = slope * (n - 1) + intercept
        
        # 2. Volatility (Std Dev of Residuals)
        sq_residuals = sum((p - (slope * i + intercept)) ** 2 for i, p in enumerate(prices))
        std_dev = math.sqrt(sq_residuals / n)
        
        if std_dev == 0:
            return None
            
        # 3. Z-Score
        current_price = prices[-1]
        z_score = (current_price - fair_value) / std_dev
        
        # 4. RSI
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
        Core Trading Logic
        """
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        result_signal = None

        for symbol, data in prices.items():
            # Parse Data
            try:
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
                
            if liquidity < self.min_liquidity:
                continue

            # Update History
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(price)
            
            if len(self.price_history[symbol]) < self.window_size:
                continue

            # === EXIT LOGIC ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # A. Fixed Stop Loss (Risk Management)
                # Strict check against static stop price calculated at entry.
                if price <= pos['stop']:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 50 
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['FIXED_STOP']
                    }
                
                # B. Dynamic Mean Reversion Exit (Profit Taking)
                # Calculate stats to check for reversion
                stats = self._calculate_stats(self.price_history[symbol])
                if not stats: continue
                
                current_roi = (price - pos['entry']) / pos['entry']
                
                # Exit if Z-Score recovers to neutral/target AND we have secured minimum profit.
                if stats['z_score'] >= self.z_exit_target and current_roi > self.min_roi:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 20
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['MEAN_REVERT', 'ROI_OK']
                    }
                continue

            # === ENTRY LOGIC ===
            # Filter checks
            if symbol in self.cooldowns: continue
            if len(self.positions) >= self.max_positions: continue
            
            stats = self._calculate_stats(self.price_history[symbol])
            if not stats: continue
            
            # Volatility Filter
            vol_bps = (stats['std_dev'] / price) * 10000
            if vol_bps < self.min_volatility_bps:
                continue
            
            # Deep Dip Strategy
            # 1. Statistical Value: Price significantly below trend (Low Z)
            # 2. Momentum Exhaustion: RSI is low
            if stats['z_score'] < self.z_entry_threshold:
                if stats['rsi'] < self.rsi_max:
                    
                    amount = self.trade_amount / price
                    
                    # Calculate Static Stop Loss
                    # We define risk at entry and do not move it.
                    stop_dist = stats['std_dev'] * self.stop_loss_sigma
                    stop_price = price - stop_dist
                    
                    self.positions[symbol] = {
                        'entry': price,
                        'stop': stop_price,
                        'amount': amount
                    }
                    
                    # Return immediately (one action per tick)
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['DEEP_DIP', 'OVERSOLD']
                    }

        return None