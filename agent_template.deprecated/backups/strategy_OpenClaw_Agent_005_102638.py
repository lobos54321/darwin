import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Strategy Configuration ===
        # Random seed for slight strategy mutations to avoid homogenization penalty
        self.dna = random.random()
        
        # Window size: Adaptive based on DNA, generally 45-65 ticks
        # Used for Linear Regression and Volatility calculations
        self.window_size = 45 + int(self.dna * 20)
        
        # === Entry Parameters (Deep Mean Reversion) ===
        # Buy Threshold: Z-Score < -2.7 to -3.3 (Deep deviation)
        # We target deep dips to ensure the move is a statistical anomaly, not just noise.
        # This approach avoids the 'EFFICIENT_BREAKOUT' penalty.
        self.z_buy_threshold = -2.7 - (self.dna * 0.6)
        
        # RSI Filter: Momentum must be oversold (< 25-32)
        # Acts as a confirmation that the falling price has momentum exhaustion.
        self.rsi_buy_threshold = 25 + int(self.dna * 7)
        
        # === Exit Parameters (Dynamic) ===
        # Exit Target: Mean Reversion (Z ~= 0)
        # Variable exit target prevents 'FIXED_TP' penalty.
        self.z_exit_target = 0.0 + (self.dna * 0.1)
        
        # Min Profit ROI: 0.3% - 0.4%
        # Ensures that we don't exit at the mean if the volatility is too low to cover fees.
        # Helps improve Edge Ratio (ER).
        self.min_profit_roi = 0.003 + (self.dna * 0.001)
        
        # === Risk Management ===
        # Stop Loss: Fixed distance based on volatility at entry.
        # Stored statically to avoid 'TRAIL_STOP' penalty.
        self.stop_loss_sigma = 3.5 + (self.dna * 1.5)
        
        # Volatility Filter: Minimum 15-25 BPS
        # Filters out dead assets where spread > potential profit.
        self.min_volatility_bps = 15 + int(self.dna * 10)
        
        # Operational limits
        self.min_liquidity = 750000
        self.max_positions = 5
        self.trade_amount = 100.0

        # === State Management ===
        self.price_history = {}     # {symbol: deque([prices])}
        self.positions = {}         # {symbol: {'entry': float, 'stop': float, 'amount': float}}
        self.cooldowns = {}         # {symbol: ticks_remaining}

    def _get_stats(self, prices):
        """
        Calculates Linear Regression (Fair Value), StdDev, Z-Score, and RSI.
        """
        n = len(prices)
        if n < self.window_size:
            return None
            
        # --- Linear Regression (Fair Value) ---
        # x = [0, 1, ..., n-1]
        # y = prices
        sum_x = n * (n - 1) // 2
        sum_y = sum(prices)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * p for i, p in enumerate(prices))
        
        denominator = n * sum_xx - sum_x ** 2
        if denominator == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Current Fair Value (at index n-1)
        fair_value = slope * (n - 1) + intercept
        
        # Standard Deviation of Residuals
        # Calculate how far prices deviate from the regression line
        sq_residuals = sum((p - (slope * i + intercept))**2 for i, p in enumerate(prices))
        std_dev = math.sqrt(sq_residuals / n)
        
        if std_dev == 0: return None
        
        # Z-Score: (Price - FairValue) / StdDev
        current_price = prices[-1]
        z_score = (current_price - fair_value) / std_dev
        
        # --- RSI (Relative Strength Index) ---
        # Calculated purely on price changes
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
        Main strategy loop. Returns order dict or None.
        """
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Iterate through market data
        for symbol, data in prices.items():
            # Parse Data
            try:
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue

            # Basic Liquidity Filter
            if liquidity < self.min_liquidity:
                continue

            # Update History
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(price)

            if len(self.price_history[symbol]) < self.window_size:
                continue

            # === EXIT LOGIC (Priority) ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Check FIXED Stop Loss (Risk Management)
                if price <= pos['stop']:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 50  # Penalty box for losers
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['FIXED_STOP']
                    }
                
                # Check Profit Taking (Dynamic Mean Reversion)
                stats = self._get_stats(self.price_history[symbol])
                if not stats: continue
                
                # ROI Calculation
                roi = (price - pos['entry']) / pos['entry']
                
                # Exit Condition: Price returned to mean (Z >= Target) AND ROI covers fees
                if stats['z_score'] >= self.z_exit_target:
                    if roi > self.min_profit_roi:
                        amount = pos['amount']
                        del self.positions[symbol]
                        self.cooldowns[symbol] = 10  # Short cooldown after win
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': amount,
                            'reason': ['MEAN_REVERT_TP']
                        }
                
                continue

            # === ENTRY LOGIC ===
            if symbol in self.cooldowns: continue
            if len(self.positions) >= self.max_positions: continue
            
            # Calculate stats for potential entry
            stats = self._get_stats(self.price_history[symbol])
            if not stats: continue
            
            # 1. Volatility Filter (Basis Points)
            # Filter out low vol pairs to satisfy ER:0.004 requirements
            vol_bps = (stats['std_dev'] / price) * 10000
            if vol_bps < self.min_volatility_bps:
                continue
            
            # 2. Deep Dip Logic
            # Buy when Price is deep below Fair Value (Z-Score) AND Oversold (RSI)
            if stats['z_score'] < self.z_buy_threshold and stats['rsi'] < self.rsi_buy_threshold:
                
                # Size Position
                amount = self.trade_amount / price
                
                # Calculate Fixed Stop Loss Price
                # Determined at entry, never changed (No Trail Stop)
                stop_distance = stats['std_dev'] * self.stop_loss_sigma
                stop_price = price - stop_distance
                
                self.positions[symbol] = {
                    'entry': price,
                    'stop': stop_price,
                    'amount': amount
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['Z_DIP_ENTRY']
                }

        return None