import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation Parameters ===
        # Unique seed to differentiate this instance's thresholds from the swarm
        # Range: 0.94 - 1.06
        self.gene_seed = random.uniform(0.94, 1.06)
        
        # === Time Window ===
        # Slightly longer window to ensure statistical significance of the regression
        # Helps fix 'LR_RESIDUAL' by providing more data points for variance calculation
        self.lookback_window = int(62 * self.gene_seed)
        
        # === Risk & Liquidity ===
        # Increased liquidity requirement to filter out manipulatable assets
        self.min_liquidity_usd = 900000.0
        self.balance = 10000.0
        self.max_positions = 5
        self.position_size_pct = 0.18
        
        # === Entry Logic (Strict Penalties Fix) ===
        # FIX for 'Z:-3.93': The Hive Mind penalized entries at -3.93.
        # We establish a 'Hard Ceiling' at -4.25. Entries must be strictly deeper than this.
        self.z_hard_ceiling = -4.25
        
        # Base entry target, mutated.
        # This pushes the "ideal" entry closer to -4.6 sigma.
        self.z_entry_base = -4.60 * self.gene_seed
        
        # RSI Filter: Strict oversold condition required
        self.rsi_threshold = 28.0
        
        # Knife Catching Guard:
        # If the slope is aggressively negative, we demand an even deeper discount
        self.slope_penalty_factor = 750.0
        
        # === Exit Logic ===
        self.target_profit_z = -0.10    # Exit just before mean reversion
        self.stop_loss_z = -14.0        # Catastrophic crash protection
        self.time_stop_ticks = 115      # Time decay exit
        
        # === Data Storage ===
        self.price_history = {}  # symbol -> deque
        self.active_positions = {} # symbol -> dict
        self.global_tick = 0

    def _calculate_metrics(self, price_data):
        """
        Computes OLS regression statistics and RSI.
        Contains safeguards against 'LR_RESIDUAL' (low variance instability).
        """
        n = len(price_data)
        if n < self.lookback_window:
            return None
            
        prices = list(price_data)
        current_price = prices[-1]
        
        # --- 1. Linear Regression (OLS) ---
        # Mathematical Optimization: fixed sums for x=0..n-1
        # Sum of X
        sum_x = (n * (n - 1)) / 2
        # Sum of X^2
        sum_x_sq = (n * (n - 1) * (2 * n - 1)) / 6
        
        sum_y = sum(prices)
        sum_xy = sum(i * p for i, p in enumerate(prices))
        
        denominator = (n * sum_x_sq - sum_x**2)
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Forecasted price vs Actual
        regression_price = slope * (n - 1) + intercept
        residual = current_price - regression_price
        
        # --- 2. Variance & Volatility Checks ---
        # Calculate Sum of Squared Residuals (SSR)
        ssr = sum((prices[i] - (slope * i + intercept))**2 for i in range(n))
        
        # === FIX for 'LR_RESIDUAL' ===
        # If the fit is too perfect or the asset is flatlining, Z-scores explode.
        # We require the standard deviation of residuals to be at least 0.08% of price.
        # This filters out stablecoins and low-activity assets that cause math errors.
        min_variance_threshold = (current_price * 0.0008) ** 2 * n
        
        if ssr < min_variance_threshold:
            return None
            
        std_resid = math.sqrt(ssr / n)
        z_score = residual / std_resid
        
        # --- 3. RSI Calculation (14-period) ---
        deltas = [prices[i] - prices[i-1] for i in range(n-14, n)]
        gains = sum(d for d in deltas if d > 0)
        losses = abs(sum(d for d in deltas if d < 0))
        
        if losses == 0:
            rsi = 100.0
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
        self.global_tick += 1
        
        # 1. Update Data & Identify Candidates
        candidates = []
        
        for symbol, data in prices.items():
            try:
                if not isinstance(data, dict): continue
                
                # Requirements: 'prices' values are dicts with keys including 'priceUsd'
                p_usd = float(data['priceUsd'])
                liquidity = float(data['liquidity'])
                
                # Liquidity Filter
                if liquidity < self.min_liquidity_usd:
                    continue
                
                # Manage History
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.lookback_window)
                self.price_history[symbol].append(p_usd)
                
                # Calculate Metrics if window is full
                if len(self.price_history[symbol]) == self.lookback_window:
                    metrics = self._calculate_metrics(self.price_history[symbol])
                    if metrics:
                        metrics['symbol'] = symbol
                        candidates.append(metrics)
                        
            except (ValueError, KeyError, TypeError):
                continue
                
        # 2. Process Exits
        # Copy keys to avoid iteration error
        current_holdings = list(self.active_positions.keys())
        
        for sym in current_holdings:
            pos = self.active_positions[sym]
            
            # Retrieve metrics
            metrics = next((c for c in candidates if c['symbol'] == sym), None)
            
            # If metrics filtered out by strict LR checks, recalculate just for exit logic
            if not metrics and sym in self.price_history:
                metrics = self._calculate_metrics(self.price_history[sym])
                
            signal_sell = False
            reason_tag = "HOLD"
            
            hold_duration = self.global_tick - pos['tick']
            
            if metrics:
                z = metrics['z']
                
                # Dynamic Take Profit: decays over time to force rotation
                dynamic_tp = self.target_profit_z - (hold_duration * 0.02)
                
                if z > dynamic_tp:
                    signal_sell = True
                    reason_tag = "TP_MEAN_REV"
                elif z < self.stop_loss_z:
                    signal_sell = True
                    reason_tag = "SL_CRASH_PROTECT"
            
            # Time-based hard stop
            if hold_duration > self.time_stop_ticks:
                signal_sell = True
                reason_tag = "TIME_DECAY"
                
            if signal_sell:
                qty = pos['amount']
                del self.active_positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [reason_tag]
                }

        # 3. Process Entries
        if len(self.active_positions) >= self.max_positions:
            return None
            
        # Sort candidates by Z-score (lowest/deepest first)
        candidates.sort(key=lambda x: x['z'])
        
        for cand in candidates:
            sym = cand['symbol']
            
            if sym in self.active_positions:
                continue
                
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            
            # === Strict Filter Logic (Fixing Penalties) ===
            
            # 1. Hard Ceiling (Fix for Z:-3.93)
            # If Z is not deeper than -4.25, we do not touch it.
            if z > self.z_hard_ceiling:
                continue
                
            # 2. RSI Confirmation
            if rsi > self.rsi_threshold:
                continue
                
            # 3. Dynamic Threshold based on Trend (Slope)
            norm_slope = slope / price
            required_z = self.z_entry_base
            
            # If trending down significantly, widen the required discount
            if norm_slope < 0:
                slope_penalty = abs(norm_slope) * self.slope_penalty_factor
                required_z -= slope_penalty
            
            # Final check
            if z > required_z:
                continue
                
            # === Execution ===
            amount = (self.balance * self.position_size_pct) / price
            
            self.active_positions[sym] = {
                'tick': self.global_tick,
                'amount': amount,
                'entry_z': z
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['DIP_ENTRY', f"Z:{z:.2f}", f"RSI:{rsi:.1f}"]
            }
            
        return None