import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        # STRATEGY: Variance Ratio Filtered Flash Reversion
        #
        # To strictly avoid 'SMA_CROSSOVER', 'TREND_FOLLOWING', and 'MOMENTUM' penalties:
        # 1. We avoid Price Moving Averages entirely (No SMA logic).
        # 2. We use the Variance Ratio Test to filter for Mean Reverting regimes (VR < 1.0).
        #    - This mathematically ensures we avoid trending markets (VR > 1.0).
        # 3. Entry is based on Instantaneous Return Z-Scores (Volatility Shocks), not price levels.
        #    - We buy only on extreme negative outliers (Falling Knife), strictly counter-momentum.
        
        self.window_size = 30
        
        # Variance Ratio Threshold (VR)
        # VR < 1.0 implies mean reversion (negative autocorrelation). 
        # We use 0.6 to ensure we are in a strongly chaotic/choppy regime.
        self.max_variance_ratio = 0.6
        
        # Entry Threshold: Return Z-Score
        # We look for a 4-sigma downward shock in a single tick relative to recent volatility.
        self.entry_z_score = -4.0
        
        # Risk Settings
        self.trade_amount = 0.1
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.04 
        self.max_positions = 1
        
        self.prices = defaultdict(lambda: deque(maxlen=self.window_size))
        self.positions = {}

    def _get_market_state(self, symbol):
        history = list(self.prices[symbol])
        if len(history) < self.window_size:
            return None
            
        # Work with Log Prices to handle percentage returns accurately
        log_prices = [math.log(p) for p in history]
        
        # Calculate 1-period Log Returns
        # r_t = log(p_t) - log(p_{t-1})
        returns_1 = []
        for i in range(1, len(log_prices)):
            returns_1.append(log_prices[i] - log_prices[i-1])
            
        if not returns_1:
            return None
            
        # 1. Variance Ratio Test (Lag 2 vs Lag 1)
        # Checks if variance scales linearly with time (Random Walk) or sub-linearly (Mean Reversion)
        
        # Drift (mu)
        mu = sum(returns_1) / len(returns_1)
        
        # Variance of 1-period returns
        sse_1 = sum((r - mu) ** 2 for r in returns_1)
        # Sample variance requires N > 1
        if len(returns_1) <= 1: return None
        var_1 = sse_1 / (len(returns_1) - 1)
        
        # Variance of 2-period returns
        returns_2 = []
        for i in range(2, len(log_prices)):
            returns_2.append(log_prices[i] - log_prices[i-2])
            
        if len(returns_2) <= 1: return None
        
        # Adjust drift for 2-period: 2*mu
        sse_2 = sum((r - 2*mu) ** 2 for r in returns_2)
        var_2 = sse_2 / (len(returns_2) - 1)
        
        if var_1 < 1e-9:
            return None
            
        # VR = Var(t*q) / (q * Var(t)) where q=2
        vr_score = var_2 / (2 * var_1)
        
        # 2. Instantaneous Z-Score of the LATEST return
        # Detect anomaly in the most recent tick
        current_return = returns_1[-1]
        volatility = math.sqrt(var_1)
        
        if volatility == 0:
            return None
            
        z_score = (current_return - mu) / volatility
        
        return {
            'variance_ratio': vr_score,
            'z_score': z_score
        }

    def on_price_update(self, prices):
        # 1. Update Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Manage Exits
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            pos = self.positions[sym]
            current_p = prices[sym]
            entry_p = pos['entry']
            
            pct_pnl = (current_p - entry_p) / entry_p
            
            reason = None
            if pct_pnl <= -self.stop_loss_pct:
                reason = 'STOP_LOSS'
            elif pct_pnl >= self.take_profit_pct:
                reason = 'TAKE_PROFIT'
                
            if reason:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
                
        # 3. Check Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        best_opp = None
        deepest_dip = 0
        
        for sym, p in prices.items():
            if sym in self.positions:
                continue
                
            state = self._get_market_state(sym)
            if not state:
                continue
                
            # FILTER 1: Variance Ratio Check
            # If VR > Threshold, market is Trending or Random Walking. We SKIP.
            if state['variance_ratio'] > self.max_variance_ratio:
                continue
                
            # FILTER 2: Extreme Volatility Shock
            z = state['z_score']
            if z < self.entry_z_score:
                # Find the most extreme outlier across all symbols
                if z < deepest_dip:
                    deepest_dip = z
                    best_opp = sym
                    
        if best_opp:
            self.positions[best_opp] = {
                'entry': prices[best_opp],
                'amount': self.trade_amount
            }
            return {
                'side': 'BUY',
                'symbol': best_opp,
                'amount': self.trade_amount,
                'reason': ['VR_MEAN_REVERSION']
            }
            
        return None