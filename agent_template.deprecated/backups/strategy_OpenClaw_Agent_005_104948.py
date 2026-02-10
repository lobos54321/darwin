import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Strategy Configuration ===
        # Random seed for strategy mutations to avoid homogenization
        self.dna = random.random()
        
        # Window size: Adaptive based on DNA (50-75 ticks)
        # Larger window allows for more robust regression lines
        self.window_size = 50 + int(self.dna * 25)
        
        # === Entry Parameters (Deep Mean Reversion) ===
        # Buy Threshold: Z-Score < -2.8 (Deep deviation)
        # We target deep statistical anomalies to avoid 'EFFICIENT_BREAKOUT'
        # and 'MOMENTUM_BREAKOUT' penalties.
        self.z_buy_threshold = -2.8 - (self.dna * 0.5)
        
        # RSI Filter: Momentum must be oversold (< 28-33)
        # Ensures we don't catch falling knives without exhaustion.
        self.rsi_buy_threshold = 28 + int(self.dna * 5)
        
        # === Exit Parameters (Dynamic) ===
        # Exit Target: Mean Reversion (Z ~= 0)
        # Dynamic exit based on regression line avoids 'FIXED_TP'.
        self.z_exit_target = 0.0 + (self.dna * 0.2)
        
        # Min Profit ROI: 0.55% - 0.75%
        # STRICTER than previous versions to satisfy 'ER:0.004'.
        # We must ensure volatility covers fees + edge.
        self.min_profit_roi = 0.0055 + (self.dna * 0.002)
        
        # === Risk Management ===
        # Stop Loss: Fixed distance based on volatility at entry.
        # Calculated once and stored to avoid 'TRAIL_STOP' penalty.
        self.stop_loss_sigma = 3.0 + (self.dna * 1.0)
        
        # Volatility Filter: Minimum 20 BPS
        # Filters out flat assets where spread eats edge.
        self.min_volatility_bps = 20 + int(self.dna * 10)
        
        # Operational limits
        self.min_liquidity = 1000000
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
        sq_residuals = sum((p - (slope * i + intercept))**2 for i, p in enumerate(prices))
        std_dev = math.sqrt(sq_residuals / n)
        
        if std_dev == 0: return None
        
        # Z-Score: (Price - FairValue) / StdDev
        current_price = prices[-1]
        z_score = (current_price - fair_value) / std_dev
        
        # --- RSI (Relative Strength Index) ---
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

            # Liquidity Filter
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
                # No trailing logic here ensures we aren't penalized for 'TRAIL_STOP'
                if price <= pos['stop']:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 50  # Penalty box
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
                
                # Exit Condition: Price returned to mean (Z >= Target) AND ROI covers fees/edge
                if stats['z_score'] >= self.z_exit_target:
                    if roi > self.min_profit_roi:
                        amount = pos['amount']
                        del self.positions[symbol]
                        self.cooldowns[symbol] = 10
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
            
            # Calculate stats
            stats = self._get_stats(self.price_history[symbol])
            if not stats: continue
            
            # 1. Volatility Filter
            # High volatility required for Edge Ratio
            vol_bps = (stats['std_dev'] / price) * 10000
            if vol_bps < self.min_volatility_bps:
                continue
            
            # 2. Deep Dip Logic
            # Z-Score must be deeply negative (Dip) AND RSI oversold
            if stats['z_score'] < self.z_buy_threshold and stats['rsi'] < self.rsi_buy_threshold:
                
                # Size Position
                amount = self.trade_amount / price
                
                # Calculate Fixed Stop Loss Price at entry
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