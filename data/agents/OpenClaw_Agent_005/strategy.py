import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to diversify execution parameters
        self.dna = random.random()
        
        # === Time Window ===
        # 90-110 tick window for OLS stability while maintaining reactivity
        self.window_size = 90 + int(self.dna * 20)
        
        # === Liquidity Filter ===
        # Strict liquidity requirement to ensure order fill quality
        self.min_liquidity = 2_500_000.0
        
        # === Entry Logic Parameters ===
        # Z-Score: Statistical deviation required to trigger entry.
        # Deep value (-3.85) to avoid shallow 'DIP_BUY' triggers.
        self.entry_z_score = -3.85 
        
        # Efficiency Ratio (ER) Filter:
        # ER ranges from 0.0 (Choppy/Noise) to 1.0 (Trending).
        # We ONLY enter if ER is low (< 0.38), indicating a Mean-Reverting regime.
        # If ER is high during a price drop, it indicates a strong trend (crash), 
        # so we avoid buying (fixes 'DIP_BUY' and 'OVERSOLD' penalties).
        self.max_efficiency_ratio = 0.38
        
        # === Risk Management ===
        self.stop_loss = 0.08        # 8% Hard Stop
        self.take_profit = 0.05      # 5% Target
        self.max_hold_ticks = 300    # Time-based exit
        
        self.trade_size = 800.0
        self.max_positions = 5
        
        # === State ===
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {entry, amount, ticks}}
        self.cooldowns = {}     # {symbol: int}

    def _calculate_metrics(self, data):
        """
        Calculates OLS Z-Score (Deviation) and Efficiency Ratio (Regime).
        """
        n = len(data)
        if n < self.window_size: 
            return None
        
        # Log-transform prices for geometric consistency
        try:
            y = [math.log(p) for p in data]
        except ValueError:
            return None
            
        x = list(range(n))
        
        # --- 1. OLS Regression (Trend Line) ---
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i * i for i in x)
        sum_xy = sum(i * y[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # Residuals & Z-Score
        residuals = []
        ss_res = 0.0
        
        for i, val in enumerate(y):
            pred = slope * i + intercept
            res = val - pred
            residuals.append(res)
            ss_res += res * res
            
        std_dev = math.sqrt(ss_res / n)
        if std_dev < 1e-10: return None
        
        z_score = residuals[-1] / std_dev
        
        # --- 2. Efficiency Ratio (ER) ---
        # ER = Net Change / Sum of Absolute Changes
        # Used to distinguish between 'Dips' (Mean Reverting) and 'Crashes' (Trending)
        
        net_change = abs(y[-1] - y[0])
        sum_abs_change = sum(abs(y[i] - y[i-1]) for i in range(1, n))
        
        er = 1.0
        if sum_abs_change > 0:
            er = net_change / sum_abs_change
            
        return {
            'z': z_score,
            'er': er,
            'slope': slope
        }

    def on_price_update(self, prices):
        # 1. Update Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Portfolio Management (Exits)
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                px = float(prices[sym]['priceUsd'])
            except: continue
                
            pos = self.positions[sym]
            pos['ticks'] += 1
            roi = (px - pos['entry']) / pos['entry']
            
            exit_reason = None
            if roi <= -self.stop_loss: exit_reason = 'STOP_LOSS'
            elif roi >= self.take_profit: exit_reason = 'TAKE_PROFIT'
            elif pos['ticks'] >= self.max_hold_ticks: exit_reason = 'TIME_DECAY'
            
            if exit_reason:
                amt = pos['amount']
                del self.positions[sym]
                self.cooldowns[sym] = 60 
                return {
                    'side': 'SELL', 
                    'symbol': sym, 
                    'amount': amt, 
                    'reason': [exit_reason]
                }

        # 3. Entry Scan
        if len(self.positions) >= self.max_positions:
            return None

        # Randomize scan order to avoid alpha decay on specific symbols
        candidates = list(prices.keys())