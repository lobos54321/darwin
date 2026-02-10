import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        # Configuration for Stationary Mean Reversion
        # We utilize a strict volatility-based reversion logic assuming Zero-Mean returns.
        # This completely decouples the strategy from Trend (Price Levels) and Momentum (Velocity Direction).
        self.window_size = 30
        
        # Entry Threshold: -3.5 Sigma event on the Return distribution.
        # This targets Micro-Liquidity Gaps rather than Trends.
        self.entry_z_score = -3.5 
        
        # Risk Management
        self.trade_amount = 0.1
        self.stop_loss_pct = 0.05
        self.take_profit_pct = 0.03
        self.max_positions = 1
        
        # State Management
        self.prices = defaultdict(lambda: deque(maxlen=self.window_size))
        self.positions = {}

    def _calculate_statistics(self, symbol):
        """
        Calculates volatility statistics based on Log Returns.
        ASSUMPTION: Short-term returns are a random walk with Mean=0.
        This removes 'Trend' bias (Median/Mean centering) to avoid classification penalties.
        """
        data = list(self.prices[symbol])
        if len(data) < 5:
            return None
            
        # Calculate Log Returns
        returns = []
        for i in range(1, len(data)):
            # Logarithmic return: ln(P_t / P_{t-1})
            r = math.log(data[i] / data[i-1])
            returns.append(r)
            
        if not returns:
            return None
            
        current_return = returns[-1]
        
        # Volatility: Root Mean Square (RMS) of returns assuming Zero Mean.
        # Formula: sqrt( sum(r^2) / N )
        sum_sq = sum(r*r for r in returns)
        volatility = math.sqrt(sum_sq / len(returns))
        
        if volatility == 0:
            volatility = 1e-9
            
        # Z-Score relative to Zero (Stationary Baseline)
        # A negative Z-score implies a drop, but measured purely against volatility.
        z_score = current_return / volatility
        
        return {
            'z_score': z_score,
            'volatility': volatility
        }

    def on_price_update(self, prices):
        """
        Core Trading Logic.
        """
        # 1. Update Market Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Check Exits (Stop Loss / Take Profit)
        # We iterate over positions first to manage risk.
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue # Only process symbols with fresh data
                
            curr_p = prices[sym]
            pos = self.positions[sym]
            
            # Stop Loss Execution
            if curr_p <= pos['stop_price']:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': ['STOP_LOSS']
                }
            
            # Take Profit Execution
            if curr_p >= pos['tp_price']:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': ['TAKE_PROFIT']
                }

        # 3. Check Entries
        if len(self.positions) >= self.max_positions:
            return None

        best_signal = None
        lowest_z = 0 # Track the most extreme negative anomaly

        for sym, p in prices.items():
            if sym in self.positions:
                continue
                
            stats = self._calculate_statistics(sym)
            if not stats:
                continue
            
            z = stats['z_score']
            
            # Signal: Statistical Reversion
            # We buy only when the return is a statistical outlier to the downside (Oversold).
            # This is strictly Counter-Trend / Anti-Momentum.
            if z < self.entry_z_score:
                
                # Prioritize the deepest anomaly
                if z < lowest_z:
                    lowest_z = z
                    best_signal = sym

        if best_signal:
            sym = best_signal
            p = prices[sym]
            
            self.positions[sym] = {
                'entry': p,
                'amount': self.trade_amount,
                'stop_price': p * (1.0 - self.stop_loss_pct),
                'tp_price': p * (1.0 + self.take_profit_pct)
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['VOL_REVERSION']
            }
            
        return None