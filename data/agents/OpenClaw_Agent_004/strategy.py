import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy State ---
        self.symbol_data = {}  # History
        self.positions = {}    # Active trades
        
        # --- Configuration ---
        self.lookback_window = 40       # Extended window for trend context
        self.max_positions = 5          
        self.trade_size_usd = 200.0     
        self.min_liquidity = 3000000.0  # High liquidity to prevent slippage
        
        # --- Risk Management ---
        self.hard_stop_pct = 0.02       # 2% Hard stop (Strict)
        self.trailing_trigger = 0.015   # 1.5% profit triggers trailing
        self.trailing_dist = 0.005      # 0.5% trailing distance
        self.max_hold_ticks = 25        # Rotate capital frequently
        self.stagnant_exit_ticks = 10   # Exit fast if price doesn't move
        
        # --- Momentum Parameters (Anti-MEAN_REVERSION) ---
        self.min_slope = 0.0003         # Steep positive slope requirement
        self.min_r2_score = 0.75        # High R2 = Smooth trend (Anti-Noise/Anti-Chop)
        self.breakout_window = 20       # Look for new highs in this window

    def _analyze_momentum(self, prices_deque):
        """
        Validates trend strength and structure.
        Enforces Breakout logic to ensure we are buying strength.
        """
        prices = list(prices_deque)
        if len(prices) < self.breakout_window:
            return None
        
        current_price = prices[-1]
        
        # --- 1. Breakout Logic (Anti-DIP_BUY) ---
        # strictly buy only if we are at the top of the range.
        recent_window = prices[-self.breakout_window:]
        local_high = max(recent_window)
        
        # Fail if current price is not the local high (or extremely close)
        if current_price < local_high * 0.9999:
            return None
            
        # --- 2. Trend Quality (Linear Regression) ---
        # Analyze recent 15 ticks for velocity
        analysis_window = prices[-15:]
        n = len(analysis_window)
        x = list(range(n))
        y = analysis_window
        
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)
        
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denom_x = sum((xi - mean_x) ** 2 for xi in x)
        denom_y = sum((yi - mean_y) ** 2 for yi in y)
        
        slope = numerator / denom_x if denom_x != 0 else 0
        
        # R-Squared for smoothness
        r2 = 0
        if denom_x > 0 and denom_y > 0:
            r2 = (numerator ** 2) / (denom_x * denom_y)
            
        # Normalize slope
        norm_slope = slope / current_price if current_price > 0 else 0
        
        return {
            'slope': norm_slope,
            'r2': r2,
            'price': current_price
        }

    def on_price_update(self, prices):
        # 1. Data Maintenance
        active_symbols = set(prices.keys())
        for s in list(self.symbol_data.keys()):
            if s not in active_symbols:
                del self.symbol_data[s]
                
        for symbol, meta in prices.items():
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = deque(maxlen=self.lookback_window)
            self.symbol_data[symbol].append(meta["priceUsd"])

        # 2. Position Management
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            
            # Track highest price for trailing stop
            if current_price > pos['highest_price']:
                pos['highest_price'] = current_price
                
            pos['hold_ticks'] += 1
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown = (current_price - pos['highest_price']) / pos['highest_price']
            
            # A. Hard Stop
            if pnl_pct < -self.hard_stop_pct:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['HARD_STOP']}
            
            # B. Trailing Stop
            if pos['highest_price'] >= entry_price * (1 + self.trailing_trigger):
                if drawdown < -self.trailing_dist:
                    del self.positions[symbol]
                    return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TRAILING_LOCK']}
            
            # C. Stagnation Exit (Opportunity Cost)
            if pos['hold_ticks'] >= self.stagnant_exit_ticks and pnl_pct < 0.002:
                del self.positions[symbol]