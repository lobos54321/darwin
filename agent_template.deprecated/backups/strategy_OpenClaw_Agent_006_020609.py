import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Parameters ===
        # Unique seed for parameter mutation to avoid correlation with other bots
        self.gene_seed = random.uniform(0.92, 1.08)
        
        # === Time Window ===
        # Extended window to smooth out noise and improve regression stability
        # Base 60 ticks +/- randomization
        self.lookback_window = int(60 * self.gene_seed)
        
        # === Risk & Liquidity ===
        # Increased liquidity requirement to ensure cleaner price action
        self.min_liquidity_usd = 750000.0
        self.balance = 10000.0
        self.max_positions = 5
        self.position_size_pct = 0.18
        
        # === Entry Logic (Strict) ===
        # FIX for 'Z:-3.93': Hard cap at -4.10. No buys above this level.
        self.z_hard_ceiling = -4.10
        # Base entry target, mutated deep
        self.z_entry_base = -4.35 * self.gene_seed
        
        # RSI Filter (Oversold)
        self.rsi_threshold = 26.0
        
        # Slope Sensitivity: Penalize catching falling knives
        self.slope_penalty_factor = 850.0
        
        # === Exit Logic ===
        self.target_profit_z = 0.0      # Revert to mean
        self.stop_loss_z = -12.0        # Crash protection
        self.time_stop_ticks = 110      # Stale position exit
        
        # === Data Storage ===
        self.price_history = {}  # symbol -> deque
        self.active_positions = {} # symbol -> dict
        self.global_tick = 0

    def _calculate_metrics(self, price_data):
        """
        Computes OLS regression statistics and RSI.
        Returns None if data is insufficient or statistically unsafe (LR_RESIDUAL fix).
        """
        n = len(price_data)
        if n < self.lookback_window:
            return None
            
        prices = list(price_data)
        current_price = prices[-1]
        
        # --- 1. Linear Regression (OLS) ---
        x = list(range(n))
        y = prices
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * p for i, p in enumerate(y))
        sum_x_sq = sum(i**2 for i in x)
        
        denominator = (n * sum_x_sq - sum_x**2)
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Forecasted price vs Actual
        regression_price = slope * (n - 1) + intercept
        residual = current_price - regression_price
        
        # --- 2. Variance & Volatility Checks ---
        # Calculate Sum of Squared Residuals
        ssr = sum((prices[i] - (slope * i + intercept))**2 for i in range(n))
        variance = ssr / n
        std_dev = math.sqrt(variance)
        
        # === FIX for 'LR_RESIDUAL' ===
        # Filter out low-volatility regimes where Z-scores are mathematically unstable.
        # If std_dev is less than 0.05% of price, the signal is noise.
        min_std_dev = current_price * 0.0005
        if std_dev < min_std_dev:
            return None
            
        z_score = residual / std_dev
        
        # --- 3. RSI Calculation (14-period) ---
        if n < 15:
            return None
            
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
            'std': std_dev,
            'price': current_price
        }

    def on_price_update(self, prices):
        self.global_tick += 1
        
        # 1. Update Data & Identify Candidates
        candidates = []
        
        for symbol, data in prices.items():
            try:
                # Safe Parsing
                if not isinstance(data, dict): continue
                
                # 'prices' values are dicts with float keys per requirements
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
                
        # 2. Process Exits (Prioritize freeing capital)
        # Snapshot keys to avoid runtime modification errors
        current_holdings = list(self.active_positions.keys())
        
        for sym in current_holdings:
            pos = self.active_positions[sym]
            
            # Retrieve fresh metrics or calculate fallback
            metrics = next((c for c in candidates if c['symbol'] == sym), None)
            
            # If metrics were filtered (e.g. low vol), force recalculation for exit logic
            if not metrics and sym in self.price_history:
                metrics = self._calculate_metrics(self.price_history[sym])
                
            # Default: Hold
            signal_sell = False
            reason_tag = "HOLD"
            
            hold_duration = self.global_tick - pos['tick']
            
            if metrics:
                z = metrics['z']
                
                # Dynamic Take Profit: Lowers slightly as time passes to encourage turnover
                # Initial target 0.0, drops by 0.01 per tick
                dynamic_tp = self.target_profit_z - (hold_duration * 0.015)
                
                if z > dynamic_tp:
                    signal_sell = True
                    reason_tag = "TP_MEAN_REV"
                elif z < self.stop_loss_z:
                    signal_sell = True
                    reason_tag = "SL_CRASH_PROTECT"
            
            # Time-based hard stop
            if hold_duration > self.time_stop_ticks:
                signal_sell = True
                reason_tag = "TIME_decay"
                
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
            
            # Avoid duplicate positions
            if sym in self.active_positions:
                continue
                
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            std = cand['std']
            
            # === Strict Filter Logic ===
            
            # 1. Hard Ceiling (Fix for Z:-3.93)
            # If the dip isn't at least -4.1 sigma, ignore it immediately.
            if z > self.z_hard_ceiling:
                continue
                
            # 2. RSI Confirmation
            if rsi > self.rsi_threshold:
                continue
                
            # 3. Dynamic Threshold based on Trend (Slope)
            # Calculate normalized slope (percent change per tick)
            norm_slope = slope / price
            
            # Base requirement
            required_z = self.z_entry_base
            
            # If trending down (negative slope), require a deeper discount
            if norm_slope < 0:
                slope_penalty = abs(norm_slope) * self.slope_penalty_factor
                required_z -= slope_penalty
            
            # 4. Volatility Scaling (Mutation)
            # If asset is extremely volatile (high sigma/price), widen the band
            vol_ratio = std / price
            if vol_ratio > 0.02: # High vol regime
                required_z -= 0.5
            
            # Final check against dynamic threshold
            if z > required_z:
                continue
                
            # === Execution ===
            # Calculate position size
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