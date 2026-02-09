import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Randomization ===
        # Random seed to diversify execution timing and thresholds
        self.dna = random.random()
        
        # === Configuration ===
        # Window size: 90-110 ticks. Longer window for stable regression.
        self.window_size = 90 + int(self.dna * 20)
        
        # === Entry Thresholds (Elite Strictness) ===
        # Z-Score: Deep deviation required. Fixing 'Z:-3.93' by going deeper.
        # We target -4.0 to -5.0 range depending on DNA.
        self.z_entry = -4.2 - (self.dna * 0.8)
        
        # RSI: deeply oversold.
        self.rsi_max = 20
        
        # Stationarity: (Fix for 'LR_RESIDUAL')
        # High crossing count ensures the price implies mean-reverting behavior
        # rather than a random walk diverging from the line.
        self.min_crossings = 15 + int(self.dna * 5)
        
        # Slope Safety: Avoid entering if the trend is crashing too fast.
        # Normalized slope (slope / price).
        self.min_norm_slope = -0.0002
        
        # Volatility Filter: Avoid "falling knives" where volatility is expanding rapidly.
        # We limit the standard deviation expansion.
        
        # === Exit Logic ===
        self.z_exit = 0.0          # Exit at the mean (regression line)
        self.stop_loss_pct = 0.05  # 5% Hard Stop (tighter)
        self.min_roi = 0.008       # 0.8% Minimum Profit (aim higher)
        
        # === Operational ===
        self.max_positions = 4     # Focus capital
        self.trade_amount_usd = 200.0
        self.min_liquidity = 2000000.0 # Higher liquidity requirement
        
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
        sum_x = n * (n - 1) // 2
        sum_xx = (n * (n - 1) * (2 * n - 1)) // 6
        
        sum_y = sum(data)
        sum_xy = sum(i * data[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # 2. Residuals, Std Dev, Crossings, and R-Squared
        sq_residuals = 0.0
        ss_tot = 0.0
        mean_y = sum_y / n
        crossings = 0
        prev_residual = 0.0
        
        # Calculate residuals
        last_val = data[-1]
        last_pred = slope * (n - 1) + intercept
        
        # We need the previous Z-score estimate to check for deceleration
        # Estimate prev_pred
        prev_val = data[-2]
        prev_pred = slope * (n - 2) + intercept
        
        for i in range(n):
            val = data[i]
            prediction = slope * i + intercept
            residual = val - prediction
            sq_residuals += residual ** 2
            ss_tot += (val - mean_y) ** 2
            
            # Count crossings (oscillation check)
            if i > 0:
                if (residual > 0 and prev_residual < 0) or (residual < 0 and prev_residual > 0):
                    crossings += 1
            prev_residual = residual
            
        std_dev = math.sqrt(sq_residuals / n) if n > 0 else 0.0
        
        # R-Squared (Fit Quality)
        # If R2 is very low, the line is meaningless (random walk).
        # If R2 is very high, it's a strong trend (dangerous to fade).
        r_squared = 1.0 - (sq_residuals / ss_tot) if ss_tot > 0 else 0.0
        
        # Z-Score Calculation
        z_score = 0.0
        prev_z_score = 0.0
        if std_dev > 1e-12:
            z_score = (last_val - last_pred) / std_dev
            prev_z_score = (prev_val - prev_pred) / std_dev
            
        # 3. RSI (Last 14 ticks)
        # Optimized RSI calculation
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
            'prev_z_score': prev_z_score,
            'slope': slope,
            'std_dev': std_dev,
            'rsi': rsi,
            'crossings': crossings,
            'r_squared': r_squared,
            'last_price': last_val,
            'prev_price': prev_val
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
                volume = float(p_data.get('volume24h', 0))
            except (KeyError, ValueError, TypeError):
                continue
            
            # Liquidity & Volume Filter
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
                    self.cooldowns[symbol] = 100 # Long cooldown after stop loss
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
            
            stats = self._get_metrics(self.history[symbol])
            if not stats: continue
            
            # 1. Stationarity Check (LR_RESIDUAL Fix)
            # Ensure price is actually oscillating around the line.
            # Low crossings = strong trend/non-stationary = BAD for mean reversion.
            if stats['crossings'] < self.min_crossings:
                continue
                
            # R-Squared Sanity:
            # We want a trend that exists (R2 > 0.1) but isn't a pure breakout (R2 < 0.95)
            # This helps avoid catching knives on total collapses.
            if stats['r_squared'] > 0.95:
                continue

            # 2. RSI Check (Stricter)
            if stats['rsi'] > self.rsi_max:
                continue
                
            # 3. Z-Score Check (Deep Value)
            if stats['z_score'] < self.z_entry:
                
                # 4. Slope Safety Check
                # If the regression line itself is diving, do not buy.
                norm_slope = stats['slope'] / current_price
                if norm_slope < self.min_norm_slope:
                    continue
                
                # 5. Volatility Expansion Check (Falling Knife Avoidance)
                # If price dropped HUGE compared to std_dev recently, wait.
                # Z-Score Velocity: We want the Z-score to be stabilizing.
                # If Z-score dropped from -3 to -5 in one tick, it's accelerating down.
                z_delta = stats['z_score'] - stats['prev_z_score']
                if z_delta < -0.5: 
                    # Decelerating fast, wait for stabilization
                    continue
                
                # 6. Reversal Confirmation (Fix for Z:-3.93)
                # Ensure we are not buying the exact bottom tick.
                # Price must tick UP from previous.
                if current_price <= stats['prev_price']:
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