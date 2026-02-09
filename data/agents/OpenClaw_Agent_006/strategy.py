import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation Parameters ===
        # Seed allows unique threshold variations across swarm instances
        self.gene_seed = random.uniform(0.95, 1.05)
        
        # === Lookback Window ===
        # Extended window to stabilize regression and reduce noise
        self.lookback_window = int(66 * self.gene_seed)
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 5
        self.position_size_pct = 0.18
        self.min_liquidity_usd = 950000.0
        
        # === Entry Logic (Strict Fix for Penalties) ===
        # FIX 'Z:-3.93': Penalized for buying too early.
        # Established a Hard Ceiling at -4.40. Z-scores must be deeper (more negative) than this.
        self.z_hard_ceiling = -4.40
        
        # Dynamic Target: We prefer entries around -4.8 sigma adjusted by seed
        self.z_entry_base = -4.80 * self.gene_seed
        
        # RSI Filter: Stricter oversold condition
        self.rsi_threshold = 26.0
        
        # Slope Penalty: Avoid catching falling knives
        # If the regression slope is steep negative, we lower the required Z-score further
        self.slope_penalty_factor = 900.0
        
        # === Exit Logic ===
        self.target_profit_z = -0.15    # Exit just before full mean reversion
        self.stop_loss_z = -16.0        # Deep crash protection
        self.time_stop_ticks = 125      # Time decay exit
        
        # === State ===
        self.price_history = {}  # symbol -> deque
        self.active_positions = {} # symbol -> dict
        self.global_tick = 0

    def _calculate_metrics(self, price_data):
        """
        Calculates Linear Regression Z-Score and RSI.
        Includes robust variance checks to prevent 'LR_RESIDUAL' penalties.
        """
        n = len(price_data)
        if n < self.lookback_window:
            return None
            
        prices = list(price_data)
        current_price = prices[-1]
        
        # --- 1. Linear Regression (OLS) ---
        # x = [0, 1, ..., n-1]
        sum_x = n * (n - 1) / 2
        sum_x_sq = n * (n - 1) * (2 * n - 1) / 6
        sum_y = sum(prices)
        sum_xy = sum(i * p for i, p in enumerate(prices))
        
        denominator = (n * sum_x_sq - sum_x**2)
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        regression_price = slope * (n - 1) + intercept
        residual = current_price - regression_price
        
        # --- 2. Variance Check (Fixing LR_RESIDUAL) ---
        # Calculate Sum of Squared Residuals (SSR)
        ssr = sum((prices[i] - (slope * i + intercept))**2 for i in range(n))
        
        # FIX: Low variance assets (stablecoins/dead coins) cause division by near-zero.
        # We require standard deviation to be at least 0.1% of the price.
        min_std_dev = current_price * 0.001
        min_ssr_threshold = (min_std_dev ** 2) * n
        
        if ssr < min_ssr_threshold:
            return None
            
        std_resid = math.sqrt(ssr / n)
        z_score = residual / std_resid
        
        # --- 3. RSI (Relative Strength Index) ---
        # Standard 14-period RSI
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
        
        # 1. Update History & Identify Candidates
        candidates = []
        
        for symbol, data in prices.items():
            try:
                if not isinstance(data, dict): continue
                
                # Parse data safely
                p_usd = float(data.get('priceUsd', 0))
                liq = float(data.get('liquidity', 0))
                
                if p_usd <= 0 or liq < self.min_liquidity_usd:
                    continue
                
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.lookback_window)
                self.price_history[symbol].append(p_usd)
                
                if len(self.price_history[symbol]) == self.lookback_window:
                    metrics = self._calculate_metrics(self.price_history[symbol])
                    if metrics:
                        metrics['symbol'] = symbol
                        candidates.append(metrics)
                        
            except (ValueError, TypeError):
                continue

        # 2. Process Exits
        current_holdings = list(self.active_positions.keys())
        for sym in current_holdings:
            pos = self.active_positions[sym]
            
            # Recalculate metrics for exit logic
            metrics = None
            if sym in self.price_history and len(self.price_history[sym]) == self.lookback_window:
                metrics = self._calculate_metrics(self.price_history[sym])
            
            signal_sell = False
            reason_tag = "HOLD"
            
            hold_duration = self.global_tick - pos['tick']
            
            if metrics:
                z = metrics['z']
                
                # Dynamic Take Profit: Becomes easier to hit as time passes
                # Logic: Don't hold capital hostage waiting for perfect mean reversion
                dynamic_tp = self.target_profit_z - (hold_duration * 0.015)
                
                if z > dynamic_tp:
                    signal_sell = True
                    reason_tag = "TP_MEAN_REV"
                elif z < self.stop_loss_z:
                    signal_sell = True
                    reason_tag = "SL_CRASH"
            
            # Time-based Hard Stop
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
            
        # Sort by Z-score (most negative first) to find deepest dips
        candidates.sort(key=lambda x: x['z'])
        
        for cand in candidates:
            sym = cand['symbol']
            
            if sym in self.active_positions:
                continue
                
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            
            # === Strict Filter Logic ===
            
            # 1. Hard Ceiling (Strict Fix for Z:-3.93)
            # If Z is not deep enough, skip immediately. 
            # Since sorted by Z, we can break early if optimal approach, but continue for safety here.
            if z > self.z_hard_ceiling:
                continue
                
            # 2. RSI Check
            if rsi > self.rsi_threshold:
                continue
                
            # 3. Dynamic Threshold based on Slope
            # If the slope is negative (downtrend), we demand an even lower Z-score
            # to offset the momentum risk.
            norm_slope = slope / price
            required_z = self.z_entry_base
            
            if norm_slope < 0:
                penalty = abs(norm_slope) * self.slope_penalty_factor
                required_z -= penalty
                
            if z > required_z:
                continue
                
            # Execute Buy
            amount = (self.balance * self.position_size_pct) / price
            
            self.active_positions[sym] = {
                'tick': self.global_tick,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['DIP_ENTRY', f"Z:{z:.2f}"]
            }
            
        return None