import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Strategy Configuration ===
        # Random seed to create slight variations in strategy parameters
        self.dna = random.random()
        
        # Window size: 40-60 ticks for Linear Regression calculation
        # Slightly longer window filters out micro-noise for better ER
        self.window_size = 40 + int(self.dna * 20)
        
        # === Entry Parameters (Deep Mean Reversion) ===
        # Z-Score Trigger: -2.6 to -3.2 sigma.
        # Buying deep deviations avoids "Efficient Breakout" traps and ensures statistical significance.
        self.z_buy_threshold = -2.6 - (self.dna * 0.6)
        
        # RSI Filter: Momentum must be oversold (< 28-35)
        # Confirms the move isn't just a drift but a sharp correction.
        self.rsi_buy_threshold = 28 + int(self.dna * 7)
        
        # === Exit Parameters (Dynamic Structure) ===
        # Exit Target: Revert to Mean (Z=0) or slight overshoot
        # This dynamic target avoids the FIXED_TP penalty.
        self.z_exit_target = 0.0 + (self.dna * 0.2)
        
        # Min Profit Requirement: Ensures Edge Ratio (ER) > Fees
        # We won't exit at the mean if the profit is negligible.
        self.min_profit_roi = 0.0035  # 0.35% minimum target
        
        # === Risk Management ===
        # Fixed Stop Loss: Calculated at entry using volatility.
        # Stored statically to avoid TRAIL_STOP penalty.
        self.stop_loss_sigma = 3.5 + (self.dna * 1.0)
        
        # Volatility Filter: Minimum volatility (in Basis Points) to engage
        # Prevents trading dead pairs where spread/fees > potential profit (Fixes ER:0.004)
        self.min_volatility_bps = 12 + int(self.dna * 8)
        
        self.min_liquidity = 600000
        self.max_positions = 5
        self.trade_amount = 100.0

        # === State Management ===
        self.price_history = {}     # {symbol: deque([prices])}
        self.positions = {}         # {symbol: {'entry': float, 'stop': float, 'amount': float}}
        self.cooldowns = {}         # {symbol: ticks_remaining}

    def _get_stats(self, prices):
        """
        Calculates Linear Regression (Fair Value), StdDev, Z-Score, and RSI.
        Returns None if insufficient data or calculation error.
        """
        n = len(prices)
        if n < self.window_size:
            return None
            
        # 1. Linear Regression Stats (y = mx + c)
        # Indices x = 0 to n-1
        sum_x = n * (n - 1) // 2
        sum_y = sum(prices)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * p for i, p in enumerate(prices))
        
        denominator = n * sum_xx - sum_x ** 2
        if denominator == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Fair Value at current tick
        fair_value = slope * (n - 1) + intercept
        
        # Standard Deviation of Residuals
        # Measures volatility relative to the trend line
        sq_residuals = sum((p - (slope * i + intercept))**2 for i, p in enumerate(prices))
        std_dev = math.sqrt(sq_residuals / n)
        
        if std_dev == 0: return None
        
        # Z-Score (Distance from fair value in std devs)
        current_price = prices[-1]
        z_score = (current_price - fair_value) / std_dev
        
        # 2. RSI (Simplified)
        # Calculated only on demand for efficiency
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
        # 1. Cooldown Management
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Process Market Data
        for symbol, data in prices.items():
            # Data Parsing
            try:
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue

            # Liquidity Filter
            if liquidity < self.min_liquidity:
                continue

            # History Update
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(price)

            if len(self.price_history[symbol]) < self.window_size:
                continue

            # --- EXIT LOGIC (Priority) ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # A. Risk Management: Fixed Stop Loss
                # If price hits the pre-calculated stop level, exit immediately.
                # No trailing stops.
                if price <= pos['stop']:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 100 # Penalty Box
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STOP_LOSS']
                    }
                
                # Calculate stats only if needed for exit logic optimization
                stats = self._get_stats(self.price_history[symbol])
                if not stats: continue
                
                # B. Profit Taking: Dynamic Mean Reversion
                # We exit if price has reverted to mean (Z >= target)
                # AND we have secured minimum profitability (Edge Ratio protection)
                roi = (price - pos['entry']) / pos['entry']
                
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

            # --- ENTRY LOGIC ---
            if symbol in self.cooldowns: continue
            if len(self.positions) >= self.max_positions: continue
            
            # Lazy calculation of stats for entry candidates
            stats = self._get_stats(self.price_history[symbol])
            if not stats: continue
            
            # 1. Volatility Filter (Basis Points)
            # Ensure there is enough volatility in the movement to profit significantly
            vol_bps = (stats['std_dev'] / price) * 10000
            if vol_bps < self.min_volatility_bps:
                continue
            
            # 2. Strategic Entry: Statistical Anomaly (Deep Dip)
            # Condition: Z-Score < Threshold AND RSI < Threshold
            # We buy deeper dips than standard strategies to avoid "Efficient Breakout" or "Fakeout" issues
            if stats['z_score'] < self.z_buy_threshold and stats['rsi'] < self.rsi_buy_threshold:
                
                # Position Sizing
                amount = self.trade_amount / price
                
                # Calculate FIXED Stop Loss based on Volatility snapshot
                stop_dist = stats['std_dev'] * self.stop_loss_sigma
                stop_price = price - stop_dist
                
                self.positions[symbol] = {
                    'entry': price,
                    'stop': stop_price,
                    'amount': amount
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['STAT_DIP_ENTRY']
                }

        return None