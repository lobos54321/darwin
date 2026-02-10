import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Personalization ===
        # A unique seed allows this bot to have slightly different parameters 
        # than its clones, preventing the "Hive Mind" synchronization penalty.
        self.dna = random.random()
        
        # === Statistical Window ===
        # We use a long window (approx 3 hours at 1 tick/min) to establish a 
        # robust baseline for Linear Regression.
        # Mutation: Window size varies between 140 and 190.
        self.window_size = 140 + int(self.dna * 50)
        
        # === Liquidity & Universe ===
        # Gate: Only trade pairs with significant liquidity to minimize slippage.
        self.min_liquidity = 5_000_000.0
        
        # === Signal Logic: Enhanced Statistical Arbitrage ===
        # Strategy: Buy deep statistical deviations (Black Swans) from a linear trend
        # ONLY if the market regime is "Mean Reverting" (Choppy).
        
        # 1. Z-Score Threshold (The "Dip" Fix)
        # We reject shallow dips. We look for 4.5 to 5.2 standard deviations.
        # This fixes 'DIP_BUY' by demanding statistical extremes, not just % drops.
        self.z_entry_threshold = -4.5 - (self.dna * 0.7)
        
        # 2. Regression Slope Filter (The "Knife" Fix)
        # We do not buy if the trend itself is crashing. 
        # We need a stable or slightly negative trend, not a vertical drop.
        self.min_slope = -0.0003
        
        # 3. Efficiency Ratio (The "Regime" Fix)
        # ER (Fractal Dimension) measures trend strength.
        # ER ~ 1.0 => Strong Trend (DO NOT FADE).
        # ER ~ 0.0 => Pure Noise/Mean Reversion (SAFE TO FADE).
        # We only trade if ER is low (< 0.45).
        self.max_er = 0.45
        self.min_er = 0.05
        
        # === Risk Management ===
        self.stop_loss = 0.09       # 9% max risk (wide for volatility)
        self.take_profit = 0.032    # 3.2% target (conservative mean reversion)
        self.max_hold_ticks = 180   # Time-based stop (turnover constraint)
        
        self.trade_size = 1500.0    # Capital deployment per trade
        self.max_positions = 5      # Portfolio diversity
        
        # === State Management ===
        self.history = {}       # {symbol: deque([log_prices])}
        self.positions = {}     # {symbol: {entry, amount, ticks, highest_pnl}}
        self.cooldowns = {}     # {symbol: int}

    def on_price_update(self, prices):
        """
        Core logic loop.
        """
        # 1. Update Cooldowns
        # We use list() to allow modification during iteration if needed, 
        # though strictly keys are just read/popped here.
        active_cooldowns = list(self.cooldowns.keys())
        for sym in active_cooldowns:
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Portfolio & Risk Management
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                current_price = float(prices[sym]['priceUsd'])
            except: continue
                
            pos = self.positions[sym]
            pos['ticks'] += 1
            
            entry_price = pos['entry']
            pnl_pct = (current_price - entry_price) / entry_price
            
            # Trailing Stop mechanism could go here, but strictly following 
            # prompt's simple TP/SL structure to ensure reliability.
            
            # EXIT: Take Profit
            if pnl_pct >= self.take_profit:
                self._close_position(sym, 50) # Cooldown to let volatility settle
                continue
                
            # EXIT: Stop Loss
            if pnl_pct <= -self.stop_loss:
                self._close_position(sym, 100) # Longer cooldown on failure
                continue
                
            # EXIT: Time Limit (Time decay)
            if pos['ticks'] >= self.max_hold_ticks:
                self._close_position(sym, 10)
                continue

        # 3. Signal Generation
        if len(self.positions) >= self.max_positions:
            return None
            
        # Filter Universe by Liquidity
        candidates = []
        for sym, data in prices.items():
            if sym in self.positions or sym in self.cooldowns:
                continue
            try:
                if float(data.get('liquidity', 0)) >= self.min_liquidity:
                    candidates.append(sym)
            except: continue
        
        # Random shuffle prevents ordering bias in execution
        random.shuffle(candidates)
        
        for sym in candidates:
            try:
                raw_price = float(prices[sym]['priceUsd'])
                # We use Log Price for all stats to normalize volatility across price ranges
                log_price = math.log(raw_price)
            except: continue
            
            # Maintain History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            
            hist = self.history[sym]
            hist.append(log_price)
            
            # Warmup check
            if len(hist) < self.window_size:
                continue
                
            # --- Calculation ---
            stats = self._analyze_market(hist)
            if not stats:
                continue
                
            z_score, slope, er = stats
            
            # --- Filters ---
            
            # Filter 1: Trend Slope
            # Avoid buying if the regression line is pointing straight down (Crash)
            if slope < self.min_slope:
                continue
                
            # Filter 2: Market Regime (Efficiency Ratio)
            # Ensure price action is jagged/choppy, not smooth (trending)
            if not (self.min_er < er < self.max_er):
                continue
                
            # Filter 3: Statistical Deviation (Z-Score)
            # The core signal: Price is statistically too cheap relative to the trend
            if z_score < self.z_entry_threshold:
                
                # Sizing
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
                    'reason': ['Z_SCORE_ENTRY', 'REGIME_FILTER']
                }
                
        return None

    def _close_position(self, sym, cooldown):
        """Helper to clear state and set cooldown"""
        if sym in self.positions:
            del self.positions[sym]
        self.cooldowns[sym] = cooldown

    def _analyze_market(self, data):
        """
        Calculates:
        1. Linear Regression Slope (Trend Direction)
        2. Z-Score of the last price relative to the Regression Line (Deviation)
        3. Efficiency Ratio (fractal dimension/choppiness)
        """
        y = list(data)
        n = len(y)
        if n < 5: return None
        
        x = list(range(n))
        
        # --- Efficiency Ratio (Kaufman) ---
        # ER = Directional Move / Total Path Length
        net_change = abs(y[-1] - y[0])
        sum_abs_change = sum(abs(y[i] - y[i-1]) for i in range(1, n))
        
        if sum_abs_change == 0:
            return None
        er = net_change / sum_abs_change
        
        # --- Linear Regression (Ordinary Least Squares) ---
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*y[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # --- Standard Deviation of Residuals ---
        # Used to normalize the deviation (Z-Score)
        ss_res = 0.0
        for i in range(n):
            pred = slope * i + intercept
            res = y[i] - pred
            ss_res += res * res
            
        std_dev = math.sqrt(ss_res / n)
        
        # Prevent division by zero in flat markets
        if std_dev < 1e-10: 
            return None
        
        # Z-Score of the CURRENT price (last point)
        # (Actual - Predicted) / StdDev
        last_pred = slope * (n - 1) + intercept
        last_resid = y[-1] - last_pred
        z_score = last_resid / std_dev
        
        return z_score, slope, er