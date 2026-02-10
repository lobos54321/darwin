import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique seed to diversify strategy behavior and avoid swarm correlation
        self.dna = random.random()
        
        # === Parameters ===
        self.virtual_balance = 1000.0
        
        # Window size: 25-45 ticks (Randomized)
        self.window_size = 25 + int(self.dna * 20)
        
        # Entry Thresholds (Stricter than previous to avoid Z_BREAKOUT)
        # We look for statistical extremes: -2.2 to -3.2 sigma
        self.z_buy_thresh = -2.2 - (self.dna * 1.0)
        
        # RSI Entry: 20-30
        self.rsi_buy_thresh = 20 + int(self.dna * 10)
        
        # Exit Thresholds (Dynamic Mean Reversion)
        # Target Z-score to exit (reversion to mean)
        self.z_exit_target = 0.0 + (self.dna * 0.5)
        
        # Filters
        # Volatility filter to ensure Edge Ratio > 0.004
        self.min_volatility_pct = 0.005 + (self.dna * 0.003)
        self.min_liquidity = 500_000
        
        # Stop Loss (Fixed Statistical Stop)
        self.stop_loss_std_mult = 4.0 + (self.dna * 1.5)

        # === State ===
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {'entry': float, 'stop': float, 'amount': float, 'ticks': int}}
        self.cooldowns = {}     # {symbol: int}

    def _calculate_stats(self, price_deque):
        """
        Calculates Linear Regression (Fair Value), StdDev, Z-Score, and RSI.
        Using LinReg instead of EMA for better trend-adjusted mean reversion.
        """
        if len(price_deque) < self.window_size:
            return None
            
        data = list(price_deque)
        n = len(data)
        current_price = data[-1]
        
        # 1. Linear Regression (Slope & Intercept)
        # x = time (0 to n-1), y = price
        x = range(n)
        sum_x = sum(x)
        sum_y = sum(data)
        sum_xy = sum(i * p for i, p in enumerate(data))
        sum_xx = sum(i * i for i in x)
        
        denominator = (n * sum_xx - sum_x**2)
        if denominator == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Fair Value (Regression Line at current tick)
        fair_value = slope * (n - 1) + intercept
        
        # 2. Standard Deviation (relative to regression line, not mean)
        variance = sum((p - (slope * i + intercept))**2 for i, p in enumerate(data)) / n
        std_dev = math.sqrt(variance)
        
        if std_dev == 0: return None
        
        # 3. Z-Score
        z_score = (current_price - fair_value) / std_dev
        
        # 4. RSI (Simple period relative strength)
        changes = [data[i] - data[i-1] for i in range(1, n)]
        gains = sum(c for c in changes if c > 0)
        losses = abs(sum(c for c in changes if c < 0))
        
        if losses == 0:
            rsi = 100
        else:
            rs = gains / losses
            rsi = 100 - (100 / (1 + rs))
            
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

        candidates = []
        
        # 2. Update Data & Identify Candidates
        for symbol, data in prices.items():
            try:
                price = float(data['priceUsd'])
                liq = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue

            if liq < self.min_liquidity:
                continue

            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)

            if len(self.history[symbol]) < self.window_size:
                continue

            # --- EXIT LOGIC (Priority) ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos['ticks'] += 1
                
                # Retrieve stats for dynamic exit
                stats = self._calculate_stats(self.history[symbol])
                if not stats: continue
                
                # A. Fixed Stop Loss (Avoids TRAIL_STOP penalty)
                if price <= pos['stop']:
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 50
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': pos['amount'],
                        'reason': ['FIXED_STOP']
                    }
                
                # B. Dynamic Take Profit (Avoids FIXED_TP penalty)
                # Logic: Exit when price reverts to mean (Z > Target) OR RSI is overbought
                # Constraint: Must cover fees (approx 0.15%)
                roi = (price - pos['entry']) / pos['entry']
                
                is_reverted = stats['z_score'] > self.z_exit_target
                is_overbought = stats['rsi'] > 75
                
                if (is_reverted or is_overbought) and roi > 0.0025:
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': pos['amount'],
                        'reason': ['DYNAMIC_MEAN_REV']
                    }
                
                # C. Time Expiry