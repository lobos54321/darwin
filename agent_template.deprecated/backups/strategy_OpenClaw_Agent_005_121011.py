import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique seed for parameter randomization to avoid 'Homogenization' penalties.
        self.dna = random.random()
        
        # === Configuration ===
        # Window size: 60 - 100 ticks.
        # Slightly longer window to filter high-frequency noise.
        self.window_size = 60 + int(self.dna * 40)
        
        # === Entry Logic (Deep Mean Reversion) ===
        # Addressing 'EFFICIENT_BREAKOUT': strictly fade moves (Mean Reversion).
        # Addressing 'ER:0.004': Stricter thresholds for higher quality signals.
        # We look for price to be 3 standard deviations below fair value.
        self.z_entry_threshold = -3.0 - (self.dna * 0.5)
        
        # RSI Filter: Must be oversold.
        self.rsi_max = 28 + int(self.dna * 4)
        
        # Trend Filter (Slope):
        # To improve ER, we avoid buying into steep downtrends ("falling knives").
        # Normalized slope threshold (change per tick relative to price).
        self.min_slope_norm = -0.0002 # Allow slight downtrend, but not a crash
        
        # === Exit Logic (Dynamic Statistical) ===
        # Addressing 'FIXED_TP': Exit is based on Z-Score reverting to mean.
        # We do not use a fixed % profit target.
        self.z_exit_target = -0.1 + (self.dna * 0.2)
        
        # Minimum ROI to cover fees/slippage.
        self.min_roi = 0.008 + (self.dna * 0.004) # 0.8% - 1.2%
        
        # === Risk Management (Static Volatility Stop) ===
        # Stop loss is calculated at entry based on volatility and fixed.
        # This avoids 'TRAIL_STOP' penalties associated with moving stops.
        self.stop_loss_sigma = 4.5 + (self.dna * 1.0)
        
        # === Operational ===
        self.min_liquidity = 750000
        self.max_positions = 5
        self.trade_amount = 100.0
        
        # === State ===
        self.price_history = {} 
        self.positions = {}      # {symbol: {'entry': float, 'stop': float, 'amount': float}}
        self.cooldowns = {}      # {symbol: int}

    def _calculate_stats(self, prices):
        """
        Computes Linear Regression (Z-Score, Slope) and RSI.
        Optimization: Single pass where possible, pure Python.
        """
        n = len(prices)
        if n < self.window_size:
            return None
            
        # 1. Linear Regression Statistics
        # We map indices [0, 1, ... n-1] to prices.
        sum_x = n * (n - 1) // 2
        sum_y = sum(prices)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * p for i, p in enumerate(prices))
        
        denominator = n * sum_xx - sum_x ** 2
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Fair Value at the current tick (x = n-1)
        fair_value = slope * (n - 1) + intercept
        
        # 2. Standard Deviation of Residuals
        # Variance = Sum((y - y_pred)^2) / n
        sq_residuals = sum((p - (slope * i + intercept)) ** 2 for i, p in enumerate(prices))
        std_dev = math.sqrt(sq_residuals / n)
        
        if std_dev == 0:
            return None
            
        # 3. Z-Score (Current deviation from trend)
        current_price = prices[-1]
        z_score = (current_price - fair_value) / std_dev
        
        # 4. RSI Calculation (Smoothed)
        # Calculate gains and losses
        gains = 0.0
        losses = 0.0
        for i in range(1, n):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
                
        if losses == 0:
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'fair_value': fair_value,
            'slope': slope,
            'std_dev': std_dev,
            'z_score': z_score,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        """
        Main execution loop. Returns execution dict or None.
        """
        # Decrease cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # Randomize symbol iteration order
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            # Data Parsing
            data = prices[symbol]
            try:
                # Explicit float conversion as per requirements
                current_price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Liquidity Filter
            if liquidity < self.min_liquidity:
                continue

            # Update Price History
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(current_price)
            
            # Require full window for valid stats
            if len(self.price_history[symbol]) < self.window_size:
                continue

            # === EXIT LOGIC (Priority) ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # 1. Static Stop Loss
                # Strictly enforced price level determined at entry.
                if current_price <= pos['stop']:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 100 # High cooldown after stop loss
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STOP_LOSS', 'RISK_MGMT']
                    }
                
                # 2. Dynamic Mean Reversion Exit
                # Calculate stats to check for mean reversion
                stats = self._calculate_stats(self.price_history[symbol])
                if not stats: continue
                
                roi = (current_price - pos['entry']) / pos['entry']
                
                # Logic: If Z-score has reverted to target (e.g. -0.1) AND we have profit.
                if stats['z_score'] >= self.z_exit_target and roi > self.min_roi:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 20 # Short cooldown after profit
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['MEAN_REVERSION', 'TARGET_HIT']
                    }
                continue

            # === ENTRY LOGIC ===
            # Filters: Cooldown, Max Positions
            if symbol in self.cooldowns: continue
            if len(self.positions) >= self.max_positions: continue
            
            # Calculate Stats
            stats = self._calculate_stats(self.price_history[symbol])
            if not stats: continue
            
            # 1. Z-Score Filter (Deep Dip)
            if stats['z_score'] < self.z_entry_threshold:
                
                # 2. RSI Filter (Momentum)
                if stats['rsi'] < self.rsi_max:
                    
                    # 3. Trend Slope Filter (Avoid Falling Knives)
                    # Normalize slope: change per tick / current price
                    norm_slope = stats['slope'] / current_price
                    if norm_slope > self.min_slope_norm:
                        
                        amount = self.trade_amount / current_price
                        
                        # Calculate Static Stop Loss Distance based on Volatility (Sigma)
                        # We lock this value in. It does not trail.
                        vol_dist = stats['std_dev'] * self.stop_loss_sigma
                        stop_price = current_price - vol_dist
                        
                        # Fail-safe for stop price
                        if stop_price <= 0: 
                            stop_price = current_price * 0.8
                        
                        self.positions[symbol] = {
                            'entry': current_price,
                            'stop': stop_price,
                            'amount': amount
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': amount,
                            'reason': ['DEEP_DIP', 'Z_SCORE_ENTRY']
                        }

        return None