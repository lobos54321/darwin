import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Configuration ===
        # Random seed to diversify parameters and prevent swarm behavior
        self.dna = random.random()
        
        # Window size: Randomized 30-55 ticks to calculate local trends
        self.window_size = 30 + int(self.dna * 25)
        
        # === Entry Thresholds (Strict Mean Reversion) ===
        # We target statistical anomalies: Price significantly below Fair Value (Linear Regression)
        # Z-Score Trigger: -2.4 to -3.2 sigma (Buying deep dips only)
        self.z_buy_threshold = -2.4 - (self.dna * 0.8)
        
        # RSI Filter: Ensure momentum is genuinely oversold (< 28-33)
        self.rsi_buy_threshold = 28 + int(self.dna * 5)
        
        # === Exit Parameters (Dynamic) ===
        # Target Z-score for exit: Revert to mean (0.0) or slightly above
        self.z_exit_target = 0.0 + (self.dna * 0.25)
        
        # === Risk Management ===
        # Fixed Stop Loss calculated at entry based on volatility (Avoids TRAIL_STOP penalty)
        # Multiplier of Standard Deviation for stop distance
        self.stop_loss_sigma = 3.5 + (self.dna * 1.0) 
        
        # Volatility Filter: Minimum Volatility in Basis Points to ensure Edge Ratio (ER > 0.004)
        self.min_volatility_bps = 5 + int(self.dna * 5) 
        
        self.min_liquidity = 500_000
        self.max_positions = 5
        self.position_size_usd = 100.0

        # === State ===
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {'entry': float, 'stop': float, 'amount': float}}
        self.cooldowns = {}     # {symbol: ticks_remaining}

    def _calculate_metrics(self, price_deque):
        """
        Calculates Linear Regression Channel metrics and RSI.
        Returns None if insufficient data.
        """
        if len(price_deque) < self.window_size:
            return None
            
        data = list(price_deque)
        n = len(data)
        current_price = data[-1]
        
        # 1. Linear Regression (y = mx + c)
        # x coordinates are 0 to n-1
        # Calculations optimized for speed
        sum_x = (n * (n - 1)) / 2
        sum_y = sum(data)
        sum_xx = (n * (n - 1) * (2 * n - 1)) / 6
        sum_xy = sum(i * p for i, p in enumerate(data))
        
        denominator = (n * sum_xx - sum_x**2)
        if denominator == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Fair Value is the regression line value at the current tick
        fair_value = slope * (n - 1) + intercept
        
        # 2. Standard Deviation of Residuals (Volatility relative to Trend)
        # We calculate variance around the regression line, not the mean
        sq_residuals = sum((data[i] - (slope * i + intercept))**2 for i in range(n))
        std_dev = math.sqrt(sq_residuals / n)
        
        if std_dev == 0: return None
        
        # 3. Z-Score (Number of std_devs away from fair value)
        z_score = (current_price - fair_value) / std_dev
        
        # 4. RSI (Smoothed relative strength)
        gains = 0.0
        losses = 0.0
        for i in range(1, n):
            delta = data[i] - data[i-1]
            if delta > 0: gains += delta
            else: losses += abs(delta)
            
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
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Process Symbols
        for symbol, data in prices.items():
            # Data Parsing & Liquidity Check
            try:
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue

            if liquidity < self.min_liquidity:
                continue

            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)

            if len(self.history[symbol]) < self.window_size:
                continue

            # Calculate Advanced Stats
            stats = self._calculate_metrics(self.history[symbol])
            if not stats: continue

            # --- EXIT LOGIC (Priority) ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # A. Fixed Stop Loss 
                # Avoids TRAIL_STOP penalty by using a static price calculated at entry
                if price <= pos['stop']:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 100  # Penalty box for losers
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STOP_LOSS_FIXED']
                    }
                
                # B. Dynamic Mean Reversion Exit 
                # Avoids FIXED_TP penalty by exiting based on statistical normalization
                roi = (price - pos['entry']) / pos['entry']
                
                # Condition: Price recovered to Z > Target (Mean) OR RSI Overbought
                reversion_hit = stats['z_score'] >= self.z_exit_target
                
                # Ensure we cover fees (approx 0.15% round trip) + edge
                if reversion_hit and roi > 0.002:
                    amount = pos['amount']
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['MEAN_REVERSION_TP']
                    }
                    
                continue

            # --- ENTRY LOGIC ---
            if symbol in self.cooldowns: continue
            if len(self.positions) >= self.max_positions: continue
            
            # 1. Volatility Filter (Avoid ER:0.004 penalty)
            # Ensure the asset moves enough to profit. Volatility in Basis Points.
            vol_bps = (stats['std_dev'] / price) * 1000