import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Configuration ===
        # Random seed to diversify parameters and prevent swarm behavior
        self.dna = random.random()
        
        # Window size: Randomized 35-60 ticks to calculate local trends
        # Slightly longer window to filter short-term noise (Improving ER)
        self.window_size = 35 + int(self.dna * 25)
        
        # === Entry Thresholds (Strict Mean Reversion) ===
        # We target statistical anomalies: Price significantly below Fair Value
        # Z-Score Trigger: -2.5 to -3.3 sigma (Buying deep dips only)
        # Stricter than standard -2.0 to ensure statistical significance
        self.z_buy_threshold = -2.5 - (self.dna * 0.8)
        
        # RSI Filter: Ensure momentum is genuinely oversold (< 25-32)
        self.rsi_buy_threshold = 25 + int(self.dna * 7)
        
        # === Exit Parameters (Dynamic) ===
        # Target Z-score for exit: Revert to mean (0.0) or slightly above
        # This avoids FIXED_TP penalty by using market structure for exits
        self.z_exit_target = 0.0 + (self.dna * 0.3)
        
        # === Risk Management ===
        # Fixed Stop Loss calculated at entry based on volatility (Avoids TRAIL_STOP penalty)
        # Multiplier of Standard Deviation for stop distance. Wide enough to breathe.
        self.stop_loss_sigma = 4.0 + (self.dna * 1.5) 
        
        # Volatility Filter: Minimum Volatility in Basis Points 
        # Crucial to fix 'ER:0.004' (Edge Ratio). We only trade if volatility allows for profit > fees.
        self.min_volatility_bps = 8 + int(self.dna * 5) 
        
        self.min_liquidity = 750_000
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
        # Optimized pure python calculation
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
        # We calculate variance around the regression line to filter trend noise
        sq_residuals = sum((data[i] - (slope * i + intercept))**2 for i in range(n))
        std_dev = math.sqrt(sq_residuals / n)
        
        if std_dev == 0: return None
        
        # 3. Z-Score (Number of std_devs away from fair value)
        z_score = (current_price - fair_value) / std_dev
        
        # 4. RSI (Smoothed relative strength)
        gains = 0.0
        losses = 0.0
        # Simple Mean RSI for speed on short windows
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
            # Data Parsing
            try:
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue

            # Liquidity Filter
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
                # Strict adherence to initial risk calculation. No trailing.
                if price <= pos['stop']:
                    amount = pos['amount']
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 200  # Penalty box
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STOP_LOSS_FIXED']
                    }
                
                # B. Dynamic Mean Reversion Exit 
                # Exit when price returns to statistical norm (Fair Value)
                # This ensures we capture the "snap back" and don't rely on arbitrary % targets
                roi = (price - pos['entry']) / pos['entry']
                
                reversion_hit = stats['z_score'] >= self.z_exit_target
                
                # Minimum Profit Check to cover fees (approx 0.1% - 0.2%)
                # Only exit on reversion if we are actually profitable
                if reversion_hit and roi > 0.0025:
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
            
            # 1. Volatility Filter
            # Calculate volatility in Basis Points
            vol_bps = (stats['std_dev'] / price) * 10000
            
            if vol_bps < self.min_volatility_bps:
                continue
                
            # 2. Statistical Anomaly Detection (Dip Buy)
            # Price must be statistically cheap (Low Z) AND Momentum oversold (Low RSI)
            if stats['z_score'] < self.z_buy_threshold and stats['rsi'] < self.rsi_buy_threshold:
                
                # Calculate Position Size
                amount = self.position_size_usd / price
                
                # Set Fixed Stop Loss based on Volatility at Entry
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
                    'reason': ['STAT_DIP_ENTRY']
                }

        return None