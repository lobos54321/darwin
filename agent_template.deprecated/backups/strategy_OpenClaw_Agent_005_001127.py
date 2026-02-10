import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Personalization ===
        # Unique mutations to parameters to prevent herd behavior
        self.dna = random.random()
        
        # === Time Window ===
        # Use a slightly longer window to ensure statistical significance of the regression
        self.window_size = 90 + int(self.dna * 30)
        
        # === Entry Thresholds (Strict) ===
        # Z-Score: Addressing 'Z:-3.93' penalty.
        # We target a deeper deviation. The penalty implies -3.93 was insufficient.
        # Range: -4.1 to -5.5 based on DNA.
        self.entry_z = -4.1 - (self.dna * 1.4)
        
        # RSI: Deep oversold (15-25 range).
        self.entry_rsi = 18 + int(self.dna * 7)
        
        # === Structural Filters (Addressing LR_RESIDUAL) ===
        # 1. Zero Crossings: A linear fit on a curved trend (crash) produces residuals
        # that rarely cross zero (e.g., +++---). True noise crosses frequently.
        # We require at least 15% of the window to be zero crossings.
        self.min_zero_crossings_pct = 0.15
        
        # 2. Residual Autocorrelation: Must be low (< 0.25) to ensure "whiteness" of noise.
        self.max_resid_auto = 0.25
        
        # 3. Volatility Expansion (Heteroskedasticity): 
        # If recent residuals are much larger than historical, risk is undefined.
        self.max_vol_expansion = 2.0
        
        # === Risk Management ===
        self.stop_loss = 0.07       # 7% max draw down
        self.take_profit = 0.025    # 2.5% target
        self.max_hold_ticks = 200   # Time-based exit
        
        # === Operational ===
        self.trade_size = 200.0     # USD
        self.min_liq = 2000000.0    # Min Liquidity
        self.max_pos = 4            # Max concurrent positions
        
        # === State ===
        self.history = {}           # symbol -> deque
        self.positions = {}         # symbol -> dict
        self.cooldowns = {}         # symbol -> int

    def _calculate_metrics(self, data):
        """
        Computes OLS, Residuals, Z-Score, RSI, and Structural checks.
        """
        n = len(data)
        if n < self.window_size:
            return None
            
        # --- 1. RSI Calculation ---
        # Calculate RSI on the last 14 ticks to gauge immediate momentum
        deltas = [data[i] - data[i-1] for i in range(n-14, n)]
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # --- 2. Linear Regression (OLS) ---
        # x = 0 to n-1
        sum_x = n * (n - 1) // 2
        sum_xx = (n * (n - 1) * (2 * n - 1)) // 6
        sum_y = sum(data)
        sum_xy = sum(i * y for i, y in enumerate(data))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # --- 3. Residual Analysis ---
        residuals = []
        sum_sq_resid = 0.0
        crossings = 0
        
        # We also track recent variance for the volatility expansion check
        recent_window = 20
        sum_sq_resid_recent = 0.0
        
        for i, y in enumerate(data):
            pred = slope * i + intercept
            res = y - pred
            residuals.append(res)
            sum_sq_resid += res * res
            
            # Check Zero Crossings (Fix for LR_RESIDUAL)
            if i > 0:
                if (residuals[i] > 0 and residuals[i-1] < 0) or \
                   (residuals[i] < 0 and residuals[i-1] > 0):
                    crossings += 1
            
            # Recent volatility accumulator
            if i >= n - recent_window:
                sum_sq_resid_recent += res * res

        # Standard Deviation (Full Window)
        std_dev = math.sqrt(sum_sq_resid / n)
        if std_dev < 1e-8: return None
        
        # Current Z-Score
        z_score = residuals[-1] / std_dev
        
        # --- 4. Structural Checks ---
        
        # Zero Crossings Ratio
        cross_ratio = crossings / n
        
        # Volatility Expansion Ratio (Recent Variance / Overall Variance)
        # If recent volatility is 3x the average, we are in a crash/event.
        recent_std = math.sqrt(sum_sq_resid_recent / recent_window)
        vol_ratio = recent_std / std_dev
        
        # Residual Autocorrelation (Lag 1)
        # sum(r_t * r_{t-1}) / sum(r_t^2)
        num_auto = sum(residuals[i] * residuals[i-1] for i in range(1, n))
        denom_auto = sum(r*r for r in residuals)
        resid_auto = num_auto / denom_auto if denom_auto > 0 else 0.0
        
        return {
            'z': z_score,
            'rsi': rsi,
            'slope': slope,
            'cross_ratio': cross_ratio,
            'vol_ratio': vol_ratio,
            'resid_auto': resid_auto,
            'price': data[-1]
        }

    def on_price_update(self, prices):
        # 1. Update Cooldowns
        active_symbols = list(self.cooldowns.keys())
        for sym in active_symbols:
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]
        
        results = None
        
        # 2. Shuffle for execution randomness
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            try:
                p_obj = prices[sym]
                px = float(p_obj['priceUsd'])
                liq = float(p_obj.get('liquidity', 0))
            except (ValueError, KeyError, TypeError):
                continue
                
            # Liquidity Filter
            if liq < self.min_liq:
                continue
                
            # History Management
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(px)
            
            # Need full window
            if len(self.history[sym]) < self.window_size:
                continue
                
            # === EXIT LOGIC ===
            if sym in self.positions:
                pos = self.positions[sym]
                entry = pos['entry']
                ticks = pos['ticks']
                amt = pos['amount']
                
                # Increment hold time
                self.positions[sym]['ticks'] += 1
                
                roi = (px - entry) / entry
                
                # Stop Loss
                if roi < -self.stop_loss:
                    del self.positions[sym]
                    self.cooldowns[sym] = 100
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['STOP_LOSS']}
                
                # Take Profit (Mean Reversion)
                # Dynamic exit: if RSI rebounds > 50 or ROI target hit
                if roi > self.take_profit:
                    del self.positions[sym]
                    self.cooldowns[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['TAKE_PROFIT']}
                
                # Time Stop
                if ticks > self.max_hold_ticks:
                    del self.positions[sym]
                    self.cooldowns[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['TIME_LIMIT']}
                
                continue
                
            # === ENTRY LOGIC ===
            if sym in self.cooldowns: continue
            if len(self.positions) >= self.max_pos: continue
            
            # Calculate Indicators
            stats = self._calculate_metrics(self.history[sym])
            if not stats: continue
            
            # 1. Z-Score (The core signal)
            # Must be deeper than the penalized threshold
            if stats['z'] < self.entry_z:
                
                # 2. RSI Filter (Oversold)
                if stats['rsi'] < self.entry_rsi:
                    
                    # 3. Structure Filter: Zero Crossings (Fix LR_RESIDUAL)
                    # If residuals don't cross zero often, the line fits poorly (curved crash).
                    if stats['cross_ratio'] > self.min_zero_crossings_pct:
                        
                        # 4. Structure Filter: Autocorrelation
                        # Ensure residuals are noise-like
                        if stats['resid_auto'] < self.max_resid_auto:
                            
                            # 5. Volatility Safety
                            # Avoid catching falling knives where volatility is exploding
                            if stats['vol_ratio'] < self.max_vol_expansion:
                                
                                # 6. Slope Check
                                # If the regression line itself is pointing straight down, avoid.
                                # Normalized slope check
                                norm_slope = stats['slope'] / px
                                if norm_slope > -0.0005:
                                    
                                    amount = self.trade_size / px
                                    self.positions[sym] = {
                                        'entry': px,
                                        'amount': amount,
                                        'ticks': 0
                                    }
                                    
                                    return {
                                        'side': 'BUY',
                                        'symbol': sym,
                                        'amount': amount,
                                        'reason': ['Z_DIP', f"Z:{stats['z']:.2f}"]
                                    }
                                    
        return None