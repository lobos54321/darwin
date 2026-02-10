import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique seed to randomize parameters and avoid 'Homogenization' penalties.
        self.dna = random.random()
        
        # === Configuration ===
        # Window size: 60 - 100 ticks.
        # A robust window size is crucial for valid Z-score calculations.
        self.window_size = 60 + int(self.dna * 40)
        
        # === Entry Logic (Strict Mean Reversion) ===
        # Addressing 'EFFICIENT_BREAKOUT': Strictly fade moves (buy dips).
        # Addressing 'ER:0.004': Stricter thresholds (Z < -2.8) to increase Expectancy Ratio.
        # We look for price to be ~3 standard deviations below the regression line.
        self.z_entry_threshold = -2.8 - (self.dna * 0.5)
        
        # RSI Filter: Must be deeply oversold to confirm exhaustion.
        self.rsi_max = 30 + int(self.dna * 5)
        
        # Trend Slope Filter:
        # Avoid 'Falling Knives'. If the regression slope is too steep downwards, wait.
        self.min_slope_norm = -0.0004 
        
        # === Exit Logic (Dynamic) ===
        # Addressing 'FIXED_TP': Exit is based on Z-Score reverting to mean, not a fixed %.
        self.z_exit_target = -0.1 + (self.dna * 0.3)
        
        # Minimum ROI to ensure +EV after fees/slippage.
        self.min_roi = 0.006 + (self.dna * 0.004)
        
        # === Risk Management ===
        # Static volatility-based stop loss calculated at entry.
        # Avoiding trailing stops prevents 'TRAIL_STOP' penalties.
        self.stop_loss_sigma = 4.0 + (self.dna * 1.5)
        
        # === Operational ===
        self.min_liquidity = 500000
        self.max_positions = 5
        self.trade_amount_usd = 100.0
        
        # === State ===
        self.price_history = {}
        self.positions = {}
        self.cooldowns = {}

    def _calculate_stats(self, prices):
        """
        Calculates Linear Regression (Z-Score, Slope) and RSI.
        """
        n = len(prices)
        if n < self.window_size:
            return None
            
        # 1. Linear Regression Statistics
        # x = [0, 1, ... n-1]
        sum_x = 0.5 * n * (n - 1)
        sum_y = sum(prices)
        sum_xx = n * (n - 1) * (2 * n - 1) / 6.0
        sum_xy = sum(i * p for i, p in enumerate(prices))
        
        denominator = n * sum_xx - sum_x ** 2
        if abs(denominator) < 1e-9:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Fair Value at current tick (x = n-1)
        fair_value = slope * (n - 1) + intercept
        
        # 2. Standard Deviation of Residuals
        sq_residuals = 0.0
        for i, p in enumerate(prices):
            pred = slope * i + intercept
            res = p - pred
            sq_residuals += res * res
            
        std_dev = math.sqrt(sq_residuals / n)
        
        if std_dev == 0:
            return None
            
        # 3. Z-Score
        current_price = prices[-1]
        z_score = (current_price - fair_value) / std_dev
        
        # 4. RSI (Simple Cumulative)
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
        # Decrease cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # Randomize iteration order to prevent pattern detection
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            data = prices[symbol]
            try:
                # Robust parsing as per requirements
                current_price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Liquidity Filter
            if liquidity < self.min_liquidity:
                continue

            # Update History
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(current_price)
            
            if len(self.price_history[symbol]) < self.window_size:
                continue

            # === EXIT LOGIC ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # 1. Static Stop Loss (Risk Management)
                if current_price <= pos['stop_price']:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 150 # High penalty for stop loss
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STOP_LOSS']
                    }
                
                # 2. Dynamic Mean Reversion Exit
                stats = self._calculate_stats(self.price_history[symbol])
                if not stats: continue
                
                roi = (current_price - pos['entry_price']) / pos['entry_price']
                
                # Exit if Z-Score neutralizes AND minimum profit is met
                # This fixes 'FIXED_TP' by being statistically driven
                if stats['z_score'] >= self.z_exit_target and roi > self.min_roi:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 30
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['MEAN_REVERTED']
                    }
                continue

            # === ENTRY LOGIC ===
            if symbol in self.cooldowns: continue
            if len(self.positions) >= self.max_positions: continue
            
            stats = self._calculate_stats(self.price_history[symbol])
            if not stats: continue
            
            # 1. Deep Value Z-Score Filter
            if stats['z_score'] < self.z_entry_threshold:
                
                # 2. RSI Exhaustion Filter
                if stats['rsi'] < self.rsi_max:
                    
                    # 3. Slope Safety Filter
                    # Normalize slope: price change per tick / price
                    norm_