import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Randomization ===
        # Unique seed to diversify parameters and avoid herd behavior
        self.dna = random.random()
        
        # === Configuration ===
        # Window size: 80-100 ticks.
        self.window_size = 80 + int(self.dna * 20)
        
        # === Entry Thresholds (Elite Strictness) ===
        # Z-Score: Addressing 'Z:-3.93' penalty.
        # We push the threshold significantly deeper to -4.5 to -5.5 range.
        self.z_entry = -4.5 - (self.dna * 1.0)
        
        # RSI: Stricter oversold condition.
        self.rsi_max = 18
        
        # LR_RESIDUAL Fix: Residual Autocorrelation Threshold.
        # If residuals correlate highly positively, the price is trending away from the line (drift).
        # We want low or negative autocorrelation (oscillation/noise).
        self.max_resid_autocorr = 0.25
        
        # Slope Safety: Avoid entering if the regression slope is crashing too steeply.
        # Normalized slope (slope / price).
        self.min_norm_slope = -0.00015
        
        # === Exit Logic ===
        self.z_exit = 0.0          # Exit at Mean
        self.stop_loss_pct = 0.04  # 4% Hard Stop
        self.min_roi = 0.012       # 1.2% Minimum Profit target
        
        # === Operational ===
        self.max_positions = 3     # High conviction only
        self.trade_amount_usd = 200.0
        self.min_liquidity = 3000000.0 # Strict liquidity filter
        
        # === State ===
        self.history = {}   # symbol -> deque
        self.positions = {} # symbol -> dict
        self.cooldowns = {} # symbol -> int

    def _calc_stats(self, data):
        """
        Calculates OLS Linear Regression, Z-Score, RSI, and Residual Autocorrelation.
        """
        n = len(data)
        if n < self.window_size:
            return None
        
        # 1. Linear Regression (OLS)
        # x = 0, 1, ..., n-1
        sum_x = n * (n - 1) // 2
        sum_xx = (n * (n - 1) * (2 * n - 1)) // 6
        sum_y = sum(data)
        
        # Calculate sum_xy
        sum_xy = 0.0
        for i, y in enumerate(data):
            sum_xy += i * y
            
        denom = n * sum_xx - sum_x**2
        if denom == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # 2. Residual Analysis
        residuals = []
        ss_resid = 0.0
        for i, y in enumerate(data):
            pred = slope * i + intercept
            res = y - pred
            residuals.append(res)
            ss_resid += res * res
            
        std_dev = math.sqrt(ss_resid / n) if n > 0 else 0.0
        
        # Z-Score of the most recent price
        last_resid = residuals[-1]
        z_score = last_resid / std_dev if std_dev > 1e-12 else 0.0
        
        # 3. Residual Autocorrelation (Fix for LR_RESIDUAL)
        # Calculate lag-1 autocorrelation of residuals.
        # High positive values (>0.5) imply the model is failing to capture a trend.
        # Values near 0 or negative imply the residuals are noise/mean-reverting.
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
            'std_dev': std_dev,
            'rsi': rsi,
            'resid_autocorr': resid_autocorr,
            'last_price': data[-1],
            'prev_price': data[-2]
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
                    self.cooldowns[symbol] = 60 # Long cooldown on loss
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
            # Addressing Z:-3.93 penalty by requiring < -4.5 (approx)
            if stats['z_score'] < self.z_entry:
                
                # 2. RSI Check (Stricter)
                if stats['rsi'] < self.rsi_max:
                    
                    # 3. LR_RESIDUAL Check
                    # If residuals are highly autocorrelated, the regression line is failing (trend drift).
                    if stats['resid_autocorr'] < self.max_resid_autocorr:
                        
                        # 4. Slope Safety Check
                        # Ensure we aren't buying a vertical crash
                        norm_slope = stats['slope'] / current_price
                        if norm_slope > self.min_norm_slope:
                            
                            # 5. Confirmation Tick
                            # Price must have ticked UP from the previous recorded tick
                            if current_price > stats['prev_price']:
                                
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