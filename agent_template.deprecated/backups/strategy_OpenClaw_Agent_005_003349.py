import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Personalization ===
        # DNA determines the "personality" of the bot to avoid correlation with others.
        self.dna = random.random()
        
        # === Time Window ===
        # Using a window that varies by instance to prevent synchronized entry points.
        # Range: 80 to 110 ticks.
        self.window_size = 80 + int(self.dna * 30)
        
        # === Entry Thresholds (Addressing Z:-3.93) ===
        # The penalty suggests -3.93 is not deep enough or is a "trap" level.
        # We push for extreme deviations (3.5 to 4 sigma events) but calculated on Log-Price.
        # Range: -4.0 to -4.8
        self.entry_z = -4.0 - (self.dna * 0.8)
        
        # RSI: Deep oversold condition (Range 15-22).
        self.entry_rsi = 15 + int(self.dna * 7)
        
        # === Structural Filters (Addressing LR_RESIDUAL) ===
        # 1. Autocorrelation: High autocorrelation in residuals means the linear model
        #    is failing to capture a trend (e.g., exponential crash).
        #    We enforce a strict "whiteness" check on noise.
        self.max_resid_auto = 0.2
        
        # 2. Curvature / Trend Acceleration:
        #    If the slope of the last 20 ticks is significantly steeper than the full window,
        #    it's a falling knife/crash, not a mean-reversion dip.
        self.max_slope_divergence = 2.5 
        
        # === Risk Management ===
        self.stop_loss = 0.06       # 6% Hard stop
        self.take_profit = 0.022    # 2.2% Mean reversion target
        self.max_hold_ticks = 150   # Time limit to free up capital
        
        # === Operational ===
        self.trade_size = 300.0     # USD size
        self.min_liq = 1500000.0    # Liquidity filter
        self.max_pos = 5            # Max concurrent positions
        
        # === State ===
        self.history = {}           # symbol -> deque
        self.positions = {}         # symbol -> dict
        self.cooldowns = {}         # symbol -> int

    def _calculate_metrics(self, data):
        """
        Computes OLS on Log-Prices to handle exponential moves better than linear OLS.
        Returns Z-score, RSI, and structural health metrics.
        """
        n = len(data)
        if n < self.window_size:
            return None
        
        # Use Log-Prices for regression (fixes Linear fit on Exponential curves)
        log_data = [math.log(p) for p in data]
        
        # --- 1. RSI Calculation (Classic 14) ---
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

        # --- 2. OLS on Log Data ---
        # x = 0 to n-1
        sum_x = n * (n - 1) // 2
        sum_xx = (n * (n - 1) * (2 * n - 1)) // 6
        sum_y = sum(log_data)
        sum_xy = sum(i * y for i, y in enumerate(log_data))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # --- 3. Residual Analysis ---
        residuals = []
        sum_sq_resid = 0.0
        
        # Autocorrelation variables
        numerator_auto = 0.0
        denominator_auto = 0.0
        
        for i, y in enumerate(log_data):
            pred = slope * i + intercept
            res = y - pred
            residuals.append(res)
            sum_sq_resid += res * res
            
            if i > 0:
                numerator_auto += res * residuals[i-1]
        
        denominator_auto = sum_sq_resid
        
        # Standard Deviation of Residuals
        std_dev = math.sqrt(sum_sq_resid / n)
        if std_dev < 1e-9: return None # Flatline
        
        # Z-Score (Current deviation in sigmas)
        z_score = residuals[-1] / std_dev
        
        # Residual Autocorrelation (Durbin-Watson proxy)
        # If residuals are highly correlated, the trend is not linear (it's curving).
        resid_auto = abs(numerator_auto / denominator_auto) if denominator_auto > 0 else 1.0
        
        # --- 4. Short-term Slope Check (Curvature) ---
        # Calculate slope of the last 15 ticks to see if it's accelerating down
        # Simple rise/run for last segment
        short_term_window = 15
        if n > short_term_window:
            y_last = log_data[-1]
            y_start = log_data[-short_term_window]
            short_slope = (y_last - y_start) / short_term_window
        else:
            short_slope = slope

        # Ratio of short-term slope to overall slope.
        # If overall slope is flat (0) and short slope is neg, this explodes, which is good (avoids).
        # We check magnitude of difference.
        slope_diff = abs(short_slope - slope)
        
        return {
            'z': z_score,
            'rsi': rsi,
            'resid_auto': resid_auto,
            'slope': slope,
            'short_slope': short_slope,
            'price': data[-1]
        }

    def on_price_update(self, prices):
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Randomize symbol processing order
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            try:
                p_data = prices[sym]
                px = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
            except (KeyError, ValueError, TypeError):
                continue
            
            # Liquidity Gate
            if liq < self.min_liq:
                continue
                
            # History Update
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(px)
            
            # Need full window for statistical significance
            if len(self.history[sym]) < self.window_size:
                continue
            
            # === EXIT LOGIC ===
            if sym in self.positions:
                pos = self.positions[sym]
                entry_px = pos['entry']
                ticks_held = pos['ticks']
                amt = pos['amount']
                
                self.positions[sym]['ticks'] += 1
                
                roi = (px - entry_px) / entry_px
                
                # Stop Loss (Hard)
                if roi < -self.stop_loss:
                    del self.positions[sym]
                    self.cooldowns[sym] = 100 # Long cooldown after SL
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['STOP_LOSS']}
                
                # Take Profit
                if roi > self.take_profit:
                    del self.positions[sym]
                    self.cooldowns[sym] = 10 # Short cooldown after TP
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['TAKE_PROFIT']}
                
                # Time Expiration
                if ticks_held > self.max_hold_ticks:
                    del self.positions[sym]
                    self.cooldowns[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['TIME_LIMIT']}
                
                continue
            
            # === ENTRY LOGIC ===
            if len(self.positions) >= self.max_pos: continue
            if sym in self.cooldowns: continue
            
            # Calculate metrics
            stats = self._calculate_metrics(self.history[sym])
            if not stats: continue
            
            # 1. Z-Score Check (Deep Dip)
            if stats['z'] < self.entry_z:
                
                # 2. RSI Check (Oversold)
                if stats['rsi'] < self.entry_rsi:
                    
                    # 3. Residual Autocorrelation (Fix for LR_RESIDUAL)
                    # If this is high, the "dip" is likely a trend change/curve, not noise.
                    if stats['resid_auto'] < self.max_resid_auto:
                        
                        # 4. Knife Catcher Filter (Trend Acceleration)
                        # If the short-term slope is drastically more negative than the long-term trend,
                        # we are in freefall. Wait for stabilization.
                        # We allow some deviation, but not massive acceleration.
                        # Using raw slope comparison from Log Regression.
                        
                        # Valid case: Overall slope is slightly up or flat, short term is down (dip).
                        # Bad case: Overall slope is down, short term is vertically down.
                        
                        is_falling_knife = (stats['short_slope'] < stats['slope'] - 0.002) # Log slope diff
                        
                        if not is_falling_knife:
                            
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
                                'reason': [
                                    'Z_DIP', 
                                    f"Z:{stats['z']:.2f}", 
                                    f"RSI:{int(stats['rsi'])}"
                                ]
                            }

        return None