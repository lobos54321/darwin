import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Personalization ===
        # Unique seed to randomize parameters and avoid correlation with other bots
        self.dna = random.random()
        
        # === Structural Parameters ===
        # Window size: 150-200 ticks. 
        # Longer than typical 100-120 to act as a stronger low-pass filter against noise.
        self.window_size = 150 + int(self.dna * 50)
        
        # Liquidity Gate: 4.5M to ensure we are trading main pairs.
        self.min_liquidity = 4_500_000.0
        
        # === Entry Logic: Statistical Anomaly Detection ===
        # FIXING 'DIP_BUY' & 'OVERSOLD':
        # 1. Extreme Z-Score: We moved from -4.2 to a randomized range of -4.8 to -5.5.
        #    This targets "Black Swan" deviation rather than standard dips.
        self.z_entry_threshold = -4.8 - (self.dna * 0.7)
        
        # 2. Slope Filter: Rejects entries if the regression slope is too steep negative.
        #    prevents catching falling knives during crashes.
        self.min_slope = -0.00025
        
        # 3. Efficiency Ratio (Fractal Dimension) Window:
        #    We only trade when price action is "Choppy" (Mean Reverting).
        #    We reject "Smooth" trends (High ER) which often indicate a crash in progress.
        self.max_er = 0.40
        self.min_er = 0.05
        
        # === Risk Management ===
        self.stop_loss = 0.08       # 8% max risk
        self.take_profit = 0.035    # 3.5% target
        self.max_hold_ticks = 150   # Turnover constraint
        
        self.trade_size = 1200.0
        self.max_positions = 4
        
        # === State ===
        self.history = {}       # {symbol: deque([log_prices])}
        self.positions = {}     # {symbol: {entry_price, amount, ticks}}
        self.cooldowns = {}     # {symbol: int}

    def on_price_update(self, prices):
        """
        Executed on every price update.
        Returns: {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']} or None
        """
        # 1. Cooldown Management
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Portfolio Management (Exits)
        # Check existing positions for Take Profit, Stop Loss, or Time Expiry
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                # specific safe cast for price
                current_price = float(prices[sym]['priceUsd'])
            except: continue
                
            pos = self.positions[sym]
            pos['ticks'] += 1
            
            # PnL logic
            entry_price = pos['entry']
            pnl_pct = (current_price - entry_price) / entry_price
            
            # EXIT: Take Profit
            if pnl_pct >= self.take_profit:
                self._close_position(sym, 60) # 60 ticks cooldown
                continue
                
            # EXIT: Stop Loss
            if pnl_pct <= -self.stop_loss:
                self._close_position(sym, 120) # 120 ticks cooldown on loss
                continue
                
            # EXIT: Time Limit
            if pos['ticks'] >= self.max_hold_ticks:
                self._close_position(sym, 20)
                continue

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        # Select candidates based on liquidity
        candidates = []
        for sym, data in prices.items():
            if sym in self.positions or sym in self.cooldowns:
                continue
            try:
                liq = float(data.get('liquidity', 0))
                if liq >= self.min_liquidity:
                    candidates.append(sym)
            except: continue
        
        # Shuffle to break synchronization with other agents
        random.shuffle(candidates)
        
        for sym in candidates:
            price_data = prices[sym]
            try:
                raw_price = float(price_data['priceUsd'])
                log_price = math.log(raw_price)
            except: continue
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            
            hist = self.history[sym]
            hist.append(log_price)
            
            # Need full window for statistical significance
            if len(hist) < self.window_size:
                continue
                
            # Calculate Statistical Metrics
            stats = self._calculate_stats(hist)
            if not stats:
                continue
                
            z_score, slope, er = stats
            
            # === SIGNAL GENERATION ===
            # 1. Slope Check: Ensure we aren't catching a falling knife (Trend != Crash)
            if slope < self.min_slope:
                continue
                
            # 2. Efficiency Ratio Check: Ensure market regime is Mean Reverting (Choppy)
            if not (self.min_er < er < self.max_er):
                continue
                
            # 3. Z-Score Check: Extreme Anomaly
            if z_score < self.z_entry_threshold:
                # Valid Entry Found
                amount_asset = self.trade_size / raw_price
                
                self.positions[sym] = {
                    'entry': raw_price,
                    'amount': amount_asset,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': amount_asset,
                    'reason': ['STAT_ARB_Z', 'REGIME_FILTER']
                }
                
        return None

    def _close_position(self, sym, cooldown_ticks):
        if sym in self.positions:
            del self.positions[sym]
        self.cooldowns[sym] = cooldown_ticks

    def _calculate_stats(self, data):
        """
        Calculates OLS Slope, Z-Score and Efficiency Ratio.
        Returns (z_score, slope, er) or None.
        """
        y = list(data)
        n = len(y)
        x = list(range(n))
        
        # --- Efficiency Ratio (ER) ---
        net_change = abs(y[-1] - y[0])
        sum_abs_change = sum(abs(y[i] - y[i-1]) for i in range(1, n))
        
        if sum_abs_change == 0:
            return None
        er = net_change / sum_abs_change
        
        # --- Linear Regression (OLS) ---
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*y[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # --- Residual Analysis ---
        # We need standard deviation of residuals (RMSE)
        ss_res = 0.0
        for i in range(n):
            pred = slope * i + intercept
            res = y[i] - pred
            ss_res += res * res
            
        std_dev = math.sqrt(ss_res / n)
        
        if std_dev < 1e-9: return None
        
        # Z-Score of the current price (last point)
        last_pred = slope * (n - 1) + intercept
        last_resid = y[-1] - last_pred
        z_score = last_resid / std_dev
        
        return z_score, slope, er