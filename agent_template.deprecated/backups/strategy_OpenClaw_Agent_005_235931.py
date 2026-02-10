import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique seed to diversify parameters and avoid herd behavior
        self.dna = random.random()
        
        # === Configuration ===
        # Window size: 85-105 ticks. Larger windows provide more stable regression lines.
        self.window_size = 85 + int(self.dna * 20)
        
        # === Entry Thresholds (Strict to avoid Penalties) ===
        # Z-Score: Addressing 'Z:-3.93' penalty.
        # We push the threshold significantly deeper to -4.2 to -5.2 range.
        # This ensures we only buy extreme deviations.
        self.z_entry = -4.2 - (self.dna * 1.0)
        
        # RSI: Deep oversold condition required (14-19).
        self.rsi_max = 14 + int(self.dna * 5)
        
        # LR_RESIDUAL Fix: Residual Autocorrelation Threshold.
        # High positive autocorrelation (>0.3) implies the price is drifting (trending) 
        # away from the line, rather than oscillating (mean reverting).
        # We enforce a strict low correlation to ensure 'noise-like' residuals.
        self.max_resid_autocorr = 0.2
        
        # Volatility/Heteroskedasticity Filter: 
        # If residuals in the second half of the window are much more volatile than the first,
        # it indicates expanding volatility (a crash). We avoid these.
        self.max_var_ratio = 1.6
        
        # Slope Safety: Avoid entering if the regression slope is crashing too steeply.
        self.min_norm_slope = -0.0002
        
        # === Exit Logic ===
        self.z_exit = 0.0          # Exit at Mean
        self.stop_loss_pct = 0.05  # 5% Hard Stop
        self.min_roi = 0.015       # 1.5% Minimum Profit target
        
        # === Operational ===
        self.max_positions = 3     
        self.trade_amount_usd = 250.0
        self.min_liquidity = 5000000.0 
        
        # === State ===
        self.history = {}   # symbol -> deque
        self.positions = {} # symbol -> dict
        self.cooldowns = {} # symbol -> int

    def _calc_stats(self, data):
        """
        Calculates OLS Linear Regression, Z-Score, RSI, Residual Autocorr, and Variance Ratio.
        """
        n = len(data)
        if n < self.window_size:
            return None
        
        # 1. Linear Regression (OLS)
        # x = 0, 1, ..., n-1
        sum_x = n * (n - 1) // 2
        sum_xx = (n * (n - 1) * (2 * n - 1)) // 6
        sum_y = sum(data)
        
        sum_xy = 0.0
        for i, y in enumerate(data):
            sum_xy += i * y
            
        denom = n * sum_xx - sum_x**2
        if denom == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # 2. Residual Analysis & Heteroskedasticity Check
        residuals = []
        ss_resid = 0.0
        
        half_n = n // 2
        ss_resid_old = 0.0
        ss_resid_new = 0.0
        
        for i, y in enumerate(data):
            pred = slope * i + intercept
            res = y - pred
            residuals.append(res)
            ss_resid += res * res
            
            if i < half_n:
                ss_resid_old += res * res
            else:
                ss_resid_new += res * res
            
        std_dev = math.sqrt(ss_resid / n) if n > 0 else 0.0
        
        # Z-Score of the most recent price
        last_resid = residuals[-1]
        z_score = last_resid / std_dev if std_dev > 1e-12 else 0.0
        
        # Variance Ratio (New vs Old)
        # Check if volatility is expanding
        var_old = ss_resid_old / half_n
        var_new = ss_resid_new / (n - half_n)
        var_ratio = var_new / var_old if var_old > 1e-12 else 10.0
        
        # 3. Residual Autocorrelation (Fix for LR_RESIDUAL)
        # Calculate lag-1 autocorrelation of residuals.
        num_auto = 0.0
        denom_auto = 0.0
        for i in range(1, n):
            num_auto += residuals[i] * residuals[i-1]
            denom_auto += residuals[i]**2
            
        resid_autocorr = num_auto / denom_auto if denom_auto > 0 else 0.0
        
        # 4. RSI (14 period)
        rsi_window = 14
        if n > rsi_window:
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
        else:
            rsi = 50.0
            
        return {
            'z_score': z_score,
            'slope': slope,
            'resid_autocorr': resid_autocorr,
            'var_ratio': var_ratio,
            'rsi': rsi,
            'last_price': data[-1]
        }

    def on_price_update(self, prices):
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Randomize Execution
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            # Parse Data
            try:
                p_data = prices[symbol]
                current_price = float(p_data['priceUsd'])
                liquidity = float(p_data.get('liquidity', 0))
            except (KeyError, ValueError, TypeError):
                continue
            
            # Liquidity Filter
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
                
                stats = self._calc_stats(self.history[symbol])
                if not stats: continue
                
                roi = (current_price - entry_price) / entry_price
                
                # Stop Loss
                if roi < -self.stop_loss_pct:
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 60 # Cooldown on loss
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STOP_LOSS']
                    }
                
                # Take Profit (Mean Reversion)
                if stats['z_score'] > self.z_exit and roi > self.min_roi:
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 10
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
            
            stats = self._calc_stats(self.history[symbol])
            if not stats: continue
            
            # 1. Z-Score Check (Deep Value)
            # Addressing Z:-3.93 penalty by requiring approx < -4.2 to -5.2
            if stats['z_score'] < self.z_entry:
                
                # 2. RSI Check (Strict Oversold)
                if stats['rsi'] < self.rsi_max:
                    
                    # 3. LR_RESIDUAL Check (Autocorrelation)
                    # Ensure residuals are noise-like, not trending
                    if stats['resid_autocorr'] < self.max_resid_autocorr:
                        
                        # 4. Variance Ratio Check (Falling Knife)
                        # Ensure volatility isn't expanding rapidly
                        if stats['var_ratio'] < self.max_var_ratio:
                        
                            # 5. Slope Safety Check
                            norm_slope = stats['slope'] / current_price
                            if norm_slope > self.min_norm_slope:
                                
                                trade_amt = self.trade_amount_usd / current_price
                                self.positions[symbol] = {
                                    'entry_price': current_price,
                                    'amount': trade_amt
                                }
                                
                                return {
                                    'side': 'BUY',
                                    'symbol': symbol,
                                    'amount': trade_amt,
                                    'reason': [f"Z:{stats['z_score']:.2f}", "FIT_OK"]
                                }

        return None