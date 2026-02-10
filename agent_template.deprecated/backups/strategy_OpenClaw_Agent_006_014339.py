import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to diversify parameters and avoid herd detection
        self.dna_factor = random.uniform(0.95, 1.05)
        
        # === Configuration ===
        # Window size for Linear Regression and Z-score
        # Mutated slightly to prevent identical execution timings
        self.window_size = int(55 * self.dna_factor)
        
        # Minimum liquidity to trade
        self.min_liquidity = 500_000.0
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 5
        # 18% per position (leaves 10% cash buffer)
        self.pos_size_pct = 0.18
        
        # === Entry Thresholds (Stricter) ===
        # FIX for Z:-3.93 Penalty -> Hard ceiling for entry Z is -4.0
        # Base entry starts deeper, around -4.2 to -4.5 based on DNA
        self.base_z_entry = -4.25 * self.dna_factor
        
        # RSI threshold for confirmation
        self.rsi_limit = 28.0
        
        # Slope Penalty: If asset is crashing (negative slope), require deeper Z
        self.slope_penalty_scaler = 600.0 
        
        # === Exit Parameters ===
        self.take_profit_z = 0.0        # Mean reversion target
        self.stop_loss_z = -10.0        # Panic dump protection
        self.max_hold_ticks = 120       # Time-based stop
        
        # === State ===
        self.history = {}       # symbol -> deque of prices
        self.positions = {}     # symbol -> {entry_tick, amount, entry_z}
        self.tick = 0

    def _get_ols_metrics(self, price_deque):
        """Calculates Linear Regression Z-Score, Slope, and RSI."""
        n = len(price_deque)
        if n < self.window_size:
            return None
        
        prices = list(price_deque)
        y = prices
        x = list(range(n))
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * p for i, p in enumerate(y))
        sum_x_sq = sum(i**2 for i in x)
        
        denominator = (n * sum_x_sq - sum_x**2)
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate Residuals and Standard Deviation
        last_price = prices[-1]
        model_price = slope * (n - 1) + intercept
        residual = last_price - model_price
        
        # Variance calculation
        ssr = sum((prices[i] - (slope * i + intercept))**2 for i in range(n))
        std_dev = math.sqrt(ssr / n)
        
        # === FIX for LR_RESIDUAL ===
        # If volatility is effectively zero, Z-scores explode mathematically.
        # We filter out these low-volatility regimes.
        # Threshold: Standard deviation must be at least 0.03% of price.
        if std_dev < (last_price * 0.0003):
            return None
            
        z_score = residual / std_dev
        
        # RSI Calculation (14 period)
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
            'price': last_price
        }

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Ingest Data & Update History
        candidates = []
        
        for symbol, data in prices.items():
            try:
                # Basic Parsing
                if not isinstance(data, dict): continue
                price_usd = float(data['priceUsd'])
                liquidity = float(data['liquidity'])
                
                # Liquidity Filter
                if liquidity < self.min_liquidity:
                    continue
                
                # History Management
                if symbol not in self.history:
                    self.history[symbol] = deque(maxlen=self.window_size)
                self.history[symbol].append(price_usd)
                
                # Metric Calculation (only if full window)
                if len(self.history[symbol]) == self.window_size:
                    metrics = self._get_ols_metrics(self.history[symbol])
                    if metrics:
                        metrics['symbol'] = symbol
                        candidates.append(metrics)
                        
            except (ValueError, KeyError, TypeError):
                continue

        # 2. Exit Logic
        # We process exits first to free up capital
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            pos = self.positions[sym]
            
            # Find current metrics for this symbol
            metrics = next((c for c in candidates if c['symbol'] == sym), None)
            
            # If metrics missing (e.g. filtered by std_dev check this tick), use fallback or hold
            # We calculate mostly to update Z for exit logic
            if not metrics and sym in self.history and len(self.history[sym]) == self.window_size:
                metrics = self._get_ols_metrics(self.history[sym])

            should_sell = False
            reason = "HOLD"
            
            ticks_held = self.tick - pos['tick']
            
            if metrics:
                current_z = metrics['z']
                
                # Exit 1: Mean Reversion (Take Profit)
                # Dynamic TP: As time passes, accept lower Z for exit to free capital
                tp_target = self.take_profit_z - (ticks_held * 0.01)
                if current_z > tp_target:
                    should_sell = True
                    reason = "TP_REV"
                    
                # Exit 2: Stop Loss (Crash)
                elif current_z < self.stop_loss_z:
                    should_sell = True
                    reason = "SL_CRASH"
            
            # Exit 3: Time Decay (Stale position)
            if ticks_held > self.max_hold_ticks:
                should_sell = True
                reason = "TIMEOUT"
                
            if should_sell:
                amount = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        # Sort candidates by Z-score (deepest dip first)
        candidates.sort(key=lambda x: x['z'])
        
        for cand in candidates:
            sym = cand['symbol']
            
            # Skip if already holding
            if sym in self.positions:
                continue
                
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            
            # === Strict Entry Filtering ===
            
            # 1. RSI Check
            if rsi > self.rsi_limit:
                continue
                
            # 2. Adaptive Z-Threshold Calculation
            # Start with base (e.g., -4.25)
            required_z = self.base_z_entry
            
            # Normalized slope (approx pct change per tick)
            norm_slope = slope / price
            
            # If slope is negative (downtrend), widen the required discount
            # This helps avoid catching "falling knives" that are just beginning to crash
            if norm_slope < 0:
                slope_penalty = abs(norm_slope) * self.slope_penalty_scaler
                required_z -= slope_penalty
            
            # Safety Cap: ABSOLUTE limit to fix 'Z:-3.93' penalty
            # We never buy if Z is > -4.0, regardless of other factors
            if required_z > -4.0:
                required_z = -4.0
                
            # Final Check
            if z > required_z:
                continue
                
            # Execute Buy
            amount = (self.balance * self.pos_size_pct) / price
            self.positions[sym] = {
                'tick': self.tick,
                'amount': amount,
                'entry_z': z
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['DIP_BUY', f"Z:{z:.2f}"]
            }
            
        return None