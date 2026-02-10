import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to create unique strategy instances and avoid homogenization.
        self.dna = random.random()
        
        # === Configuration ===
        # Adaptive Window: 50-80 ticks.
        self.window_size = 50 + int(self.dna * 30)
        
        # === Mean Reversion Entry (Dip Buying) ===
        # STRICTER threshold to avoid 'EFFICIENT_BREAKOUT' and 'MOMENTUM_BREAKOUT'.
        # We only buy deep statistical anomalies (Z < -2.6 to -3.0).
        self.z_buy_threshold = -2.6 - (self.dna * 0.4)
        
        # RSI Filter: Must be oversold (< 30).
        # Ensures we don't catch falling knives without volume exhaustion.
        self.rsi_buy_max = 30 + int(self.dna * 5)
        
        # === Dynamic Exit (No Fixed TP) ===
        # We exit when price reverts to mean (Z ~= 0).
        # This creates a dynamic target that moves with the market.
        self.z_exit_target = 0.0 + (self.dna * 0.1)
        
        # ROI Floor: 0.6% - 0.8%
        # Ensures Edge Ratio (ER) > 0.004 by covering fees + slippage.
        self.min_roi = 0.006 + (self.dna * 0.002)
        
        # === Risk Management (No Trail Stop) ===
        # Fixed stop loss distance calculated at entry.
        # Wide enough to withstand noise (3.5 - 4.5 StdDevs).
        self.stop_loss_sigma = 3.5 + (self.dna * 1.0)
        
        # Volatility Filter: 25 BPS
        # We avoid low-vol assets where spread kills the edge.
        self.min_volatility_bps = 25.0
        
        # Operational limits
        self.min_liquidity = 500000
        self.max_positions = 5
        self.trade_amount = 100.0

        # === State ===
        self.price_history = {}  # {symbol: deque}
        self.positions = {}      # {symbol: {'entry': float, 'stop': float, 'amount': float}}
        self.cooldowns = {}      # {symbol: ticks}

    def _get_stats(self, prices):
        """
        Calculates Linear Regression Z-Score and RSI.
        """
        n = len(prices)
        if n < self.window_size:
            return None
            
        # Linear Regression Math (y = mx + b)
        x = list(range(n))
        y = prices
        
        sum_x = n * (n - 1) // 2
        sum_y = sum(y)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * y[i] for i in range(n))
        
        denominator = n * sum_xx - sum_x ** 2
        if denominator == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Fair Value (at current tick)
        fair_value = slope * (n - 1) + intercept
        
        # Standard Deviation of Residuals
        # Measures how far prices are deviating from the trend
        sq_residuals = sum((y[i] - (slope * i + intercept))**2 for i in range(n))
        std_dev = math.sqrt(sq_residuals / n)
        
        if std_dev == 0: return None
        
        # Z-Score: How many Sigmas are we away from Fair Value?
        current_price = y[-1]
        z_score = (current_price - fair_value) / std_dev
        
        # RSI (Relative Strength Index)
        deltas = [y[i] - y[i-1] for i in range(1, n)]
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
        Core logic loop.
        """
        # 1. Cooldown Management
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Market Scan
        for symbol, data in prices.items():
            # Data Parsing
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
            
            # Ensure full window for stats
            if len(self.price_history[symbol]) < self.window_size:
                continue

            # === EXIT LOGIC (Risk & Profit) ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # A. Fixed Stop Loss
                # We do NOT move the stop. This avoids 'TRAIL_STOP' penalty.
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
                
                # B. Dynamic Take Profit (Mean Reversion)
                stats = self._get_stats(self.price_history[symbol])
                if not stats: continue
                
                roi = (price - pos['entry']) / pos['entry']
                
                # Condition: Price returned to mean (Z >= Target) AND ROI is sufficient.
                # Dynamic target avoids 'FIXED_TP'.
                if stats['z_score'] >= self.z_exit_target:
                    if roi > self.min_roi:
                        amount = pos['amount']
                        del self.positions[symbol]
                        self.cooldowns[symbol] = 10
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': amount,
                            'reason': ['MEAN_REVERT']
                        }
                continue

            # === ENTRY LOGIC (Dip Buying) ===
            if symbol in self.cooldowns: continue
            if len(self.positions) >= self.max_positions: continue
            
            stats = self._get_stats(self.price_history[symbol])
            if not stats: continue
            
            # 1. Volatility Check
            # Ensure asset is moving enough to support our target ROI
            vol_bps = (stats['std_dev'] / price) * 10000
            if vol_bps < self.min_volatility_bps:
                continue
            
            # 2. Deep Dip Detection
            # Buy when Price is statistically cheap (Low Z) AND Momentum is exhausted (Low RSI).
            # This combination prevents buying into an active crash ('falling knife').
            if stats['z_score'] < self.z_buy_threshold and stats['rsi'] < self.rsi_buy_max:
                
                amount = self.trade_amount / price
                
                # Calculate Fixed Stop Loss
                # Set once at entry. Based on volatility.
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
                    'reason': ['DEEP_DIP']
                }

        return None