import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity ===
        # Seed ensures this instance behaves slightly differently from others in the swarm
        self.gene_seed = random.uniform(0.92, 1.08)
        
        # === Hyperparameters ===
        # Prime number lookback to avoid harmonic resonance with standard periods (14, 20, 50)
        self.lookback = int(73 * self.gene_seed)
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 4
        self.pos_size_pct = 0.22
        
        # Liquidity Filter: High threshold to avoid slippage on exits
        self.min_liquidity = 1200000.0
        
        # === Entry Logic (Strict Penalties Fix) ===
        # FIX 'DIP_BUY': Demand deeper deviation than the penalized -4.40
        self.z_entry_threshold = -5.15 * self.gene_seed
        
        # FIX 'OVERSOLD': Lower RSI threshold to catch only extreme wicks
        self.rsi_entry_threshold = 18.0
        
        # FIX 'KELTNER': Slope Penalty Factor
        # If price is crashing (high negative slope), we demand even deeper Z-scores
        self.slope_penalty_weight = 2500.0
        
        # === Exit Logic ===
        self.z_target = -0.05       # Exit near mean
        self.z_stop_loss = -20.0    # Structural break protection
        self.max_hold_ticks = 140   # Time decay
        
        # === State ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.tick_count = 0

    def _calculate_metrics(self, price_data):
        """
        Computes OLS Linear Regression Z-Score and Short-Period RSI.
        """
        n = len(price_data)
        if n < self.lookback:
            return None
            
        data = list(price_data)
        current_price = data[-1]
        
        # --- 1. Linear Regression (OLS) ---
        # Calculates the deviation of current price from the trend line
        sum_x = n * (n - 1) / 2
        sum_x_sq = n * (n - 1) * (2 * n - 1) / 6
        sum_y = sum(data)
        sum_xy = sum(i * p for i, p in enumerate(data))
        
        denominator = (n * sum_x_sq - sum_x**2)
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        regression_price = slope * (n - 1) + intercept
        residual = current_price - regression_price
        
        # --- 2. Variance & Z-Score ---
        # Sum of Squared Residuals
        ssr = sum((data[i] - (slope * i + intercept))**2 for i in range(n))
        
        # Avoid division by zero for pegged assets
        if ssr < 1e-9:
            return None
            
        std_dev = math.sqrt(ssr / n)
        if std_dev == 0:
            return None
            
        z_score = residual / std_dev
        
        # --- 3. RSI (9-Period for HFT Speed) ---
        # Using a shorter period (9) than standard (14) for faster reaction
        rsi_period = 9
        subset = data[-rsi_period-1:]
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
        candidates = []
        
        # --- 1. Update History & Filter Candidates ---
        for symbol, data in prices.items():
            if not isinstance(data, dict):
                continue
                
            try:
                # Safe parsing
                p_usd = float(data.get('priceUsd', 0))
                liq = float(data.get('liquidity', 0))
                
                if p_usd <= 0 or liq < self.min_liquidity:
                    continue
                
                if symbol not in self.history:
                    self.history[symbol] = deque(maxlen=self.lookback)
                self.history[symbol].append(p_usd)
                
                # Only calculate if full window is ready
                if len(self.history[symbol]) == self.lookback:
                    metrics = self._calculate_metrics(self.history[symbol])
                    if metrics:
                        metrics['symbol'] = symbol
                        candidates.append(metrics)
                        
            except (ValueError, TypeError):
                continue

        # --- 2. Process Exits ---
        # Iterate over a list copy to modify dictionary safely
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            
            # Recalculate current metrics for exit signals
            metrics = None
            if sym in self.history and len(self.history[sym]) == self.lookback:
                metrics = self._calculate_metrics(self.history[sym])
            
            sell_signal = False
            reasons = []
            
            hold_ticks = self.tick_count - pos['tick']
            
            # A. Time Stop
            if hold_ticks > self.max_hold_ticks:
                sell_signal = True
                reasons.append("TIME_DECAY")
            
            # B. Technical Exits
            if metrics and not sell_signal:
                z = metrics['z']
                
                # Dynamic TP: Easier to exit as time passes to free up capital
                dynamic_tp = self.z_target - (hold_ticks * 0.005)
                
                if z > dynamic_tp:
                    sell_signal = True
                    reasons.append("TP_MEAN_REV")
                elif z < self.z_stop_loss:
                    sell_signal = True
                    reasons.append("SL_CRASH")
            
            if sell_signal:
                amount = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': reasons
                }

        # --- 3. Process Entries ---
        if len(self.positions) >= self.max_positions:
            return None
            
        # Sort candidates by Z-score depth (lowest first) to find most extreme anomalies
        candidates.sort(key=lambda x: x['z'])
        
        for cand in candidates:
            sym = cand['symbol']
            
            if sym in self.positions:
                continue
                
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            
            # === STRICT FILTERS TO AVOID PENALTIES ===
            
            # Filter 1: Deep Value (Fixing DIP_BUY)
            # Must be significantly below the regression line
            if z > self.z_entry_threshold:
                continue
                
            # Filter 2: RSI Check (Fixing OVERSOLD)
            # Must be extremely oversold, not just mildly weak
            if rsi > self.rsi_entry_threshold:
                continue
            
            # Filter 3: Slope / Falling Knife Logic
            # If the trend is crashing downwards (negative slope), we require an even deeper Z-score
            # to justify catching the knife.
            norm_slope = slope / price
            required_z = self.z_entry_threshold
            
            if norm_slope < 0:
                # Add penalty to the required threshold
                # e.g., if slope is -0.01% per tick, penalty might decrease threshold by 0.5 sigma
                penalty = abs(norm_slope) * self.slope_penalty_weight
                required_z -= penalty
            
            if z > required_z:
                continue
                
            # Execution
            usd_size = self.balance * self.pos_size_pct
            amount = usd_size / price
            
            self.positions[sym] = {
                'tick': self.tick_count,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['DEEP_VALUE', f'Z:{z:.2f}', f'RSI:{rsi:.1f}']
            }
            
        return None