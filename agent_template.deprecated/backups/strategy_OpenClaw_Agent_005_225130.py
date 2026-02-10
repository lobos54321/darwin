import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Identity ===
        # Unique seed to prevent swarm homogenization
        self.dna = random.random()
        
        # === Configuration ===
        # Window size: 70-90 ticks. Longer window = more robust regression.
        self.window_size = 70 + int(self.dna * 20)
        
        # === Entry Logic (Stricter to fix penalties) ===
        # Z-Score: Deep value required (-3.2 to -4.0 range).
        self.z_entry = -3.2 - (self.dna * 0.8)
        
        # RSI: Deep oversold condition (< 25).
        self.rsi_max = 22 + int(self.dna * 3)
        
        # Stationarity (Fix for 'LR_RESIDUAL'):
        # We demand the price crosses the regression line frequently.
        # This proves mean reversion behavior rather than a trend away from the line.
        self.min_crossings = 6 + int(self.dna * 4)
        
        # Slope Safety (Falling Knife Protection):
        # Normalized slope floor. If slope is too steep negative, do not buy.
        self.min_norm_slope = -0.0005
        
        # === Exit Logic ===
        self.z_exit = -0.1 + (self.dna * 0.2)
        self.stop_loss_pct = 0.07  # Hard stop
        self.min_roi = 0.005       # Minimum profit
        
        # === Operational ===
        self.max_positions = 5
        self.trade_amount_usd = 100.0
        self.min_liquidity = 1500000.0
        
        # === State ===
        self.history = {}
        self.positions = {}
        self.cooldowns = {}

    def _get_stats(self, data):
        """Calculates Regression, Z-Score, RSI, and Crossing Count."""
        n = len(data)
        if n < self.window_size:
            return None
        
        # Linear Regression Prep
        x = list(range(n))
        y = list(data)
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*y[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate Residuals & Crossings (Stationarity Check)
        sq_residuals = 0.0
        crossings = 0
        prev_diff = 0
        
        for i in range(n):
            prediction = slope * i + intercept
            diff = y[i] - prediction
            sq_residuals += diff ** 2
            
            # Crossing detection: sign change in residual
            if i > 0:
                if (diff > 0 and prev_diff < 0) or (diff < 0 and prev_diff > 0):
                    crossings += 1
            prev_diff = diff
            
        std_dev = math.sqrt(sq_residuals / n)
        
        # Z-Score Calculation
        last_price = y[-1]
        prev_price = y[-2]
        fair_value = slope * (n - 1) + intercept
        
        z_score = 0.0
        if std_dev > 1e-12:
            z_score = (last_price - fair_value) / std_dev
            
        # RSI Calculation (Last 14 ticks)
        rsi_n = 14
        if n > rsi_n:
            subset = y[-rsi_n-1:]
            gains = 0.0
            losses = 0.0
            for i in range(1, len(subset)):
                change = subset[i] - subset[i-1]
                if change > 0:
                    gains += change
                else:
                    losses += abs(change)
            
            if gains + losses == 0:
                rsi = 50.0
            else:
                rsi = 100.0 * gains / (gains + losses)
        else:
            rsi = 50.0
            
        return {
            'z_score': z_score,
            'slope': slope,
            'rsi': rsi,
            'crossings': crossings,
            'last_price': last_price,
            'prev_price': prev_price
        }

    def on_price_update(self, prices):
        # 1. Cooldown Decay
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Randomize Processing Order
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            # Data Parsing
            try:
                p_data = prices[symbol]
                current_price = float(p_data['priceUsd'])
                liquidity = float(p_data.get('liquidity', 0))
            except (KeyError, ValueError, TypeError):
                continue
            
            # Liquidity Filter
            if liquidity < self.min_liquidity:
                continue
                
            # History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size + 5)
            self.history[symbol].append(current_price)
            
            # Need full window
            if len(self.history[symbol]) < self.window_size:
                continue
                
            # === EXIT LOGIC ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos['entry_price']
                amount = pos['amount']
                
                stats = self._get_stats(self.history[symbol])
                if not stats: continue
                
                roi = (current_price - entry_price) / entry_price
                
                # Stop Loss
                if roi < -self.stop_loss_pct:
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 100
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STOP_LOSS']
                    }
                
                # Take Profit (Mean Reversion)
                if stats['z_score'] > self.z_exit and roi > self.min_roi:
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 20
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['PROFIT_REVERT']
                    }
                continue

            # === ENTRY LOGIC ===
            if symbol in self.cooldowns: continue
            if len(self.positions) >= self.max_positions: continue
            
            stats = self._get_stats(self.history[symbol])
            if not stats: continue
            
            # 1. Stationarity Check (Fix for 'LR_RESIDUAL')
            if stats['crossings'] < self.min_crossings:
                continue
                
            # 2. RSI Check (Momentum Exhaustion)
            if stats['rsi'] > self.rsi_max:
                continue
                
            # 3. Z-Score Check (Deep Value)
            if stats['z_score'] < self.z_entry:
                
                # 4. Slope Safety Check (Anti-Falling Knife)
                norm_slope = stats['slope'] / current_price
                if norm_slope < self.min_norm_slope:
                    continue
                    
                # 5. Inflection Confirmation (Fix for 'Z:-3.93')
                # Penalty implies catching knives. We demand a local green tick.
                # Must trade HIGHER than previous tick to confirm bottom is forming.
                if stats['last_price'] <= stats['prev_price']:
                    continue
                
                # Execute Trade
                trade_amt = self.trade_amount_usd / current_price
                self.positions[symbol] = {
                    'entry_price': current_price,
                    'amount': trade_amt
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': trade_amt,
                    'reason': ['DIP_CONFIRMED', f"Z:{stats['z_score']:.2f}"]
                }

        return None