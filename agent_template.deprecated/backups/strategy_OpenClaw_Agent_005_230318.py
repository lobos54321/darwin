import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Randomization ===
        # Unique seed to prevent swarm synchronization
        self.dna = random.random()
        
        # === Configuration ===
        # Window size: 80-100 ticks. Increased for better statistical significance.
        self.window_size = 80 + int(self.dna * 20)
        
        # === Entry Thresholds (Stricter) ===
        # Z-Score: Pushed deeper to -3.5 to -4.5 range.
        # This addresses the 'Z:-3.93' penalty by ensuring we only enter at extreme deviations.
        self.z_entry = -3.5 - (self.dna * 1.0)
        
        # RSI: Must be extremely oversold (< 25).
        self.rsi_max = 25
        
        # Stationarity: (Fix for 'LR_RESIDUAL')
        # We require the price to cross the regression line frequently.
        # Low crossings = strong trend/non-stationary = BAD for mean reversion.
        self.min_crossings = 12 + int(self.dna * 5)
        
        # Slope Safety: Avoid catching falling knives if the trend itself is collapsing.
        self.min_norm_slope = -0.0004
        
        # === Exit Logic ===
        self.z_exit = 0.0          # Exit at mean (regression line)
        self.stop_loss_pct = 0.06  # 6% Hard Stop
        self.min_roi = 0.005       # 0.5% Minimum Profit
        
        # === Operational ===
        self.max_positions = 5
        self.trade_amount_usd = 100.0
        self.min_liquidity = 1500000.0
        
        # === State ===
        self.history = {}   # symbol -> deque
        self.positions = {} # symbol -> dict
        self.cooldowns = {} # symbol -> int

    def _get_metrics(self, data):
        """
        Calculates OLS Linear Regression, Z-Score, RSI, and Crossing Count.
        Returns a dict of metrics or None if insufficient data.
        """
        n = len(data)
        if n < self.window_size:
            return None
        
        # 1. Linear Regression (OLS)
        # x = 0, 1, ..., n-1
        # Sum of x: n(n-1)/2
        sum_x = n * (n - 1) // 2
        # Sum of x^2: n(n-1)(2n-1)/6
        sum_xx = (n * (n - 1) * (2 * n - 1)) // 6
        
        sum_y = sum(data)
        sum_xy = sum(i * data[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # 2. Residuals, Std Dev, and Crossings
        sq_residuals = 0.0
        crossings = 0
        prev_residual = 0.0
        
        # We need the last predicted value for Z-score
        last_val = data[-1]
        last_pred = slope * (n - 1) + intercept
        
        for i in range(n):
            prediction = slope * i + intercept
            residual = data[i] - prediction
            sq_residuals += residual ** 2
            
            # Count crossings (change in sign of residual)
            if i > 0:
                if (residual > 0 and prev_residual < 0) or (residual < 0 and prev_residual > 0):
                    crossings += 1
            prev_residual = residual
            
        std_dev = math.sqrt(sq_residuals / n)
        
        # Z-Score Calculation
        z_score = 0.0
        if std_dev > 1e-12:
            z_score = (last_val - last_pred) / std_dev
            
        # 3. RSI (Last 14 ticks)
        rsi_window = 14
        subset = list(data)[-rsi_window-1:]
        gains = 0.0
        losses = 0.0
        for i in range(1, len(subset)):
            delta = subset[i] - subset[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
        
        if gains + losses == 0:
            rsi = 50.0
        else:
            rsi = 100.0 * gains / (gains + losses)
            
        return {
            'z_score': z_score,
            'slope': slope,
            'rsi': rsi,
            'crossings': crossings,
            'last_price': last_val,
            'prev_price': data[-2]
        }

    def on_price_update(self, prices):
        # 1. Manage Cooldowns
        active_cooldowns = {}
        for sym, ticks in self.cooldowns.items():
            if ticks > 1:
                active_cooldowns[sym] = ticks - 1
        self.cooldowns = active_cooldowns

        # 2. Randomize Execution Order
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            # Parse Data
            try:
                p_data = prices[symbol]
                current_price = float(p_data['priceUsd'])
                liquidity = float(p_data.get('liquidity', 0))
            except (KeyError, ValueError, TypeError):
                continue
            
            # Liquidity Filter
            if liquidity < self.min_liquidity:
                continue
                
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(current_price)
            
            if len(self.history[symbol]) < self.window_size:
                continue
                
            # === EXIT LOGIC ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos['entry_price']
                amount = pos['amount']
                
                # Calculate Stats
                stats = self._get_metrics(self.history[symbol])
                if not stats: continue
                
                roi = (current_price - entry_price) / entry_price
                
                # 1. Stop Loss (Safety)
                if roi < -self.stop_loss_pct:
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 60 # Long cooldown after stop loss
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STOP_LOSS']
                    }
                
                # 2. Mean Reversion Take Profit
                # Exit when price returns to regression line (Z > 0)
                if stats['z_score'] > self.z_exit and roi > self.min_roi:
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 10
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
            
            stats = self._get_metrics(self.history[symbol])
            if not stats: continue
            
            # 1. Stationarity Check (LR_RESIDUAL Fix)
            # Ensure price is actually oscillating around the line
            if stats['crossings'] < self.min_crossings:
                continue
            
            # 2. RSI Check
            if stats['rsi'] > self.rsi_max:
                continue
                
            # 3. Z-Score Check (Deep Value)
            if stats['z_score'] < self.z_entry:
                
                # 4. Slope Safety Check
                norm_slope = stats['slope'] / current_price
                if norm_slope < self.min_norm_slope:
                    continue
                
                # 5. Reversal Confirmation (Fix for Z:-3.93)
                # Ensure we are not buying the exact bottom tick.
                # Price must tick UP from previous.
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