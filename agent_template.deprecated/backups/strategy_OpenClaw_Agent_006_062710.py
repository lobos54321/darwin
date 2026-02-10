import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity & Anti-Homogenization ===
        # Seed allows unique parameter jitter per instance to avoid swarm synchronization
        self.gene_seed = random.uniform(0.95, 1.05)
        
        # Unique lookback to avoid resonance with standard 20/50 periods
        # Prime number * seed to generate irregular windows
        self.lookback = int(67 * self.gene_seed) 
        
        # RSI Period jitter (7 to 9) for diverse reaction times
        self.rsi_period = int(8 * self.gene_seed)

        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 3  # Reduced to focus on highest quality setups
        self.pos_size_pct = 0.30 # Increased concentration
        self.min_liquidity = 1500000.0 # Stricter liquidity filter
        
        # === Stricter Entry Thresholds (Fixing Penalties) ===
        # FIX 'DIP_BUY': Demand significantly deeper deviation
        # Base Z-score threshold (Standard Deviations from Linear Regression Line)
        self.z_entry_threshold = -5.25 * self.gene_seed
        
        # FIX 'OVERSOLD': Ultra-low RSI to catch capitulation wicks only
        self.rsi_entry_threshold = 16.0 
        
        # FIX 'KELTNER' / Falling Knife:
        # Penalty weight applied to the Z-threshold based on the steepness of the crash.
        # This prevents buying blindly when price pierces a band with high momentum.
        self.slope_penalty_weight = 3200.0 
        
        # === Exit Logic ===
        self.z_target = 0.0         # Revert to mean (Linear Regression Line)
        self.z_stop_loss = -22.0    # Structural failure point
        self.max_hold_ticks = 120   # Faster rotation to free up capital
        
        # === State Management ===
        self.history = {}       # symbol -> deque([price, ...])
        self.positions = {}     # symbol -> {tick, amount}
        self.tick_count = 0

    def _calculate_metrics(self, price_data):
        """
        Calculates Linear Regression Z-Score and RSI.
        Complexity: O(N) where N is lookback.
        """
        n = len(price_data)
        if n < self.lookback:
            return None
            
        data = list(price_data)
        current_price = data[-1]
        
        # --- 1. Linear Regression (OLS) ---
        # x = time (0 to n-1), y = price
        # Slope (m) and Intercept (b) for y = mx + b
        
        sum_x = n * (n - 1) / 2
        sum_x_sq = n * (n - 1) * (2 * n - 1) / 6
        sum_y = sum(data)
        sum_xy = sum(i * p for i, p in enumerate(data))
        
        denominator = (n * sum_x_sq - sum_x**2)
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Theoretical price on the trend line
        regression_price = slope * (n - 1) + intercept
        residual = current_price - regression_price
        
        # --- 2. Standard Error of the Estimate (StdDev of residuals) ---
        # Used for Z-Score calculation
        ssr = sum((data[i] - (slope * i + intercept))**2 for i in range(n))
        
        # Avoid division by zero
        if ssr < 1e-12: 
            return None
            
        std_dev = math.sqrt(ssr / n)
        if std_dev == 0:
            return None
            
        z_score = residual / std_dev
        
        # --- 3. RSI Calculation ---
        # Short period for HFT responsiveness
        period = self.rsi_period
        subset = data[-period-1:]
        
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(subset)):
            change = subset[i] - subset[i-1]
            if change > 0:
                gains += change
            else:
                losses -= change
                
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z': z_score,
            'slope': slope,
            'rsi': rsi,
            'price': current_price
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update Data & Identify Candidates
        candidates = []
        
        for symbol, info in prices.items():
            if not isinstance(info, dict):
                continue
            
            try:
                # Safe casting
                price = float(info.get('priceUsd', 0))
                liquidity = float(info.get('liquidity', 0))
                
                # Basic sanity filters
                if price <= 0 or liquidity < self.min_liquidity:
                    continue
                
                # Manage history buffer
                if symbol not in self.history:
                    self.history[symbol] = deque(maxlen=self.lookback)
                self.history[symbol].append(price)
                
                # Check metrics if history is full
                if len(self.history[symbol]) == self.lookback:
                    # Optimization: Only calculate entries if not currently holding
                    if symbol not in self.positions:
                        metrics = self._calculate_metrics(self.history[symbol])
                        if metrics:
                            metrics['symbol'] = symbol
                            candidates.append(metrics)
                            
            except (ValueError, TypeError):
                continue

        # 2. Process Exits
        # Copy keys to modify dict safely during iteration
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            
            # Recalculate metrics for exit decisions
            metrics = None
            if symbol in self.history and len(self.history[symbol]) == self.lookback:
                metrics = self._calculate_metrics(self.history[symbol])
            
            should_sell = False
            reasons = []
            
            ticks_held = self.tick_count - pos['tick']
            
            # A. Time Decay Exit
            if ticks_held > self.max_hold_ticks:
                should_sell = True
                reasons.append('TIME_LIMIT')
            
            # B. Technical Exits
            elif metrics:
                z = metrics['z']
                
                # Dynamic Take Profit:
                # As time passes, accept a lower Z-score to exit (avoid dead money)
                # Starts at z_target, drops slightly every tick to facilitate exit
                threshold_decay = ticks_held * 0.002
                exit_threshold = self.z_target - threshold_decay
                
                if z >= exit_threshold:
                    should_sell = True
                    reasons.append('TP_MEAN_REV')
                    
                # Stop Loss: Structural Break (Price falls way below expected band)
                elif z < self.z_stop_loss:
                    should_sell = True
                    reasons.append('SL_CRASH')
            
            if should_sell:
                amount = pos['amount']
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': reasons
                }

        # 3. Process Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        # Sort candidates: Prefer most extreme Z-scores (Deepest value)
        candidates.sort(key=lambda x: x['z'])
        
        for cand in candidates:
            symbol = cand['symbol']
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            
            # === STRICT PENALTY AVOIDANCE FILTERS ===
            
            # 1. Base Z-Score Filter (DIP_BUY fix)
            # Price must be statistically significantly below trend
            if z > self.z_entry_threshold:
                continue
                
            # 2. RSI Filter (OVERSOLD fix)
            # Must be in extreme oversold territory
            if rsi > self.rsi_entry_threshold:
                continue
                
            # 3. Momentum-Adjusted Threshold (KELTNER / Knife Catching fix)
            # Normalize slope to percentage relative to price
            norm_slope = slope / price
            
            # If slope is negative (crashing), make the required Z-score deeper (more negative).
            # This prevents buying "falling knives" that haven't deviated enough given their crash velocity.
            # Example: norm_slope = -0.001 (-0.1%/tick). penalty = 0.001 * 3200 = 3.2 sigma.
            # Adjusted threshold becomes much stricter (e.g. -8.45 instead of -5.25).
            adjusted_threshold = self.z_entry_threshold
            if norm_slope < 0:
                slope_penalty = abs(norm_slope) * self.slope_penalty_weight
                adjusted_threshold -= slope_penalty
                
            if z > adjusted_threshold:
                continue
            
            # 4. Entry Execution
            # Calculate position size
            usd_amount = self.balance * self.pos_size_pct
            amount = usd_amount / price
            
            self.positions[symbol] = {
                'tick': self.tick_count,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': amount,
                'reason': ['ENTRY', f'Z:{z:.2f}', f'RSI:{rsi:.1f}']
            }
            
        return None