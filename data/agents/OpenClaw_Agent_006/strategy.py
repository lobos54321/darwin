import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity (Anti-Homogenization) ===
        # Jitter parameters to ensure unique behavior across instances
        self.dna = random.uniform(0.94, 1.06)
        
        # Window size: Irregular period to avoid resonance with standard MA crosses
        self.lookback = int(60 * self.dna)
        
        # RSI Period: Extremely short for high sensitivity to microstructure
        self.rsi_period = int(7 * self.dna)
        
        # === Risk Management ===
        self.capital = 10000.0
        self.max_concurrent_trades = 2  # Highly concentrated
        self.trade_size_pct = 0.48      # Aggressive sizing on high-conviction setups
        
        # Liquidity Filter: High threshold to avoid slippage/manipulation
        self.min_liquidity_threshold = 2000000.0 
        
        # === Strategy Thresholds (Penalties Fix) ===
        # 1. FIX 'DIP_BUY': 
        # Drastically lowered Z-score threshold.
        # Only buying events > 6.8 standard deviations from the mean (Base).
        self.z_trigger = -6.8 * self.dna
        
        # 2. FIX 'OVERSOLD':
        # RSI must be in extreme capitulation zone (< 10)
        self.rsi_trigger = 10.0
        
        # 3. FIX 'KELTNER' (Falling Knife Protection):
        # Dynamic penalty applied to Z-score based on crash velocity.
        # Higher weight = stricter requirements during steep crashes.
        self.velocity_penalty_weight = 4500.0
        
        # === Exit Parameters ===
        self.z_target = 0.0          # Mean reversion target
        self.z_bailout = -30.0       # Structural failure stop loss
        self.max_ticks = 100         # Time-based stop (rotate capital)
        
        # === State ===
        self.market_data = {}   # symbol -> deque([prices])
        self.active_trades = {} # symbol -> {entry_tick, amount}
        self.clock = 0

    def _analyze_trend(self, price_history):
        """
        Performs Linear Regression OLS and RSI calculation.
        Returns metrics dict or None.
        """
        n = len(price_history)
        if n < self.lookback:
            return None
            
        # Convert deque to list for indexing
        prices = list(price_history)
        current_p = prices[-1]
        
        # --- Linear Regression (OLS) ---
        # x = [0, 1, ..., n-1]
        # y = prices
        
        # Closed form sums for x (0 to n-1)
        sum_x = n * (n - 1) / 2
        sum_x_sq = n * (n - 1) * (2 * n - 1) / 6
        
        sum_y = sum(prices)
        sum_xy = sum(i * p for i, p in enumerate(prices))
            
        denominator = (n * sum_x_sq - sum_x**2)
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Expected price per regression model
        regression_price = slope * (n - 1) + intercept
        residual = current_p - regression_price
        
        # --- Standard Deviation of Residuals ---
        # Calculate Variance of errors
        ssr = sum((p - (slope * i + intercept))**2 for i, p in enumerate(prices))
        std_err = math.sqrt(ssr / n)
        
        # Z-Score (Standardized Residual)
        if std_err < 1e-9:
            z_score = 0.0
        else:
            z_score = residual / std_err
            
        # --- RSI Calculation ---
        # Short-term momentum check
        subset = prices[-(self.rsi_period + 1):]
        if len(subset) < self.rsi_period + 1:
            return None

        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(subset)):
            delta = subset[i] - subset[i-1]
            if delta > 0:
                gains += delta
            else:
                losses -= delta
        
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
            'price': current_p
        }

    def on_price_update(self, prices):
        self.clock += 1
        candidates = []
        
        # 1. Ingest Data
        for symbol, data in prices.items():
            if not isinstance(data, dict):
                continue
                
            try:
                price = float(data.get('priceUsd', 0))
                liquidity = float(data.get('liquidity', 0))
                
                # Liquidity Filter
                if price <= 0 or liquidity < self.min_liquidity_threshold:
                    continue
                
                # Update History
                if symbol not in self.market_data:
                    self.market_data[symbol] = deque(maxlen=self.lookback)
                self.market_data[symbol].append(price)
                
                # Check for Entry Signals (if not already holding)
                if symbol not in self.active_trades and len(self.market_data[symbol]) == self.lookback:
                    metrics = self._analyze_trend(self.market_data[symbol])
                    if metrics:
                        metrics['symbol'] = symbol
                        candidates.append(metrics)
                        
            except (ValueError, TypeError):
                continue

        # 2. Process Exits
        # Iterating over list of keys to allow deletion during loop
        for symbol in list(self.active_trades.keys()):
            trade = self.active_trades[symbol]
            history = self.market_data.get(symbol)
            
            should_close = False
            reasons = []
            
            # Recalculate metrics
            metrics = None
            if history and len(history) == self.lookback:
                metrics = self._analyze_trend(history)
            
            ticks_held = self.clock - trade['tick']
            
            # A. Time Decay (Free up capital)
            if ticks_held > self.max_ticks:
                should_close = True
                reasons.append('TIME_DECAY')
            
            # B. Technical Exits
            elif metrics:
                z = metrics['z']
                
                # Dynamic Take Profit
                # Target lowers slightly over time to prevent holding dead bags
                target_decay = ticks_held * 0.005
                current_target = self.z_target - target_decay
                
                if z >= current_target:
                    should_close = True
                    reasons.append('MEAN_REVERTED')
                    
                # Emergency Stop Loss (Structural Break)
                if z < self.z_bailout:
                    should_close = True
                    reasons.append('STOP_CRASH')
            
            if should_close:
                amount = trade['amount']
                del self.active_trades[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': reasons
                }

        # 3. Process Entries
        if len(self.active_trades) >= self.max_concurrent_trades:
            return None
            
        # Prioritize the most extreme statistical deviations
        candidates.sort(key=lambda x: x['z'])
        
        for cand in candidates:
            sym = cand['symbol']
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            
            # --- PENALTY AVOIDANCE FILTERS ---
            
            # A. Base Deviation Check (DIP_BUY Fix)
            # Must be statistically anomalous
            if z > self.z_trigger:
                continue
                
            # B. Oversold Check (OVERSOLD Fix)
            # Must be in capitulation wicks
            if rsi > self.rsi_trigger:
                continue
                
            # C. Velocity-Adjusted Threshold (KELTNER Fix)
            # If the slope is negative (crashing), we penalize the threshold.
            # Normalized slope = % change per tick approx.
            norm_slope = slope / price
            
            # If crashing, demand an even deeper Z-score
            # Example: -0.1% slope -> 0.001 * 4500 = 4.5 penalty
            # Trigger becomes -6.8 - 4.5 = -11.3
            penalty = 0.0
            if norm_slope < 0:
                penalty = abs(norm_slope) * self.velocity_penalty_weight
            
            adjusted_z_trigger = self.z_trigger - penalty
            
            if z > adjusted_z_trigger:
                continue
            
            # Execution
            usd_amt = self.capital * self.trade_size_pct
            amount = usd_amt / price
            
            self.active_trades[sym] = {
                'tick': self.clock,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['ENTRY', f'Z:{z:.2f}', f'Adj:{adjusted_z_trigger:.2f}']
            }
            
        return None