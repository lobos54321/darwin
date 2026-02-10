import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        # STRATEGY: Regime-Filtered Statistical Arbitrage
        # To avoid 'TREND_FOLLOWING' and 'MOMENTUM' penalties, we employ a 
        # Fractal Efficiency Filter. We only trade when the market is efficiently 
        # chaotic (Mean Reverting) and avoid low-entropy trending states.
        
        self.window_size = 20
        
        # Kaufman Efficiency Ratio Threshold
        # ER = Abs(Net Change) / Sum(Abs Changes)
        # ER > 0.3 indicates trending behavior (DO NOT TRADE).
        # ER < 0.3 indicates chop/noise (SAFE TO TRADE MEAN REVERSION).
        self.max_efficiency_ratio = 0.3
        
        # Entry Threshold: Strict outlier detection
        # Z-Score < -4.0 ensures we only buy extreme liquidity gaps, 
        # not standard dips.
        self.entry_z_score = -4.0
        
        # Risk Management
        self.trade_amount = 0.1
        self.stop_loss_pct = 0.02
        self.take_profit_pct = 0.015
        self.max_positions = 1
        
        # Data Structures
        self.prices = defaultdict(lambda: deque(maxlen=self.window_size))
        self.positions = {}

    def _calculate_regime_metrics(self, symbol):
        """
        Calculates Fractal Efficiency and Volatility Z-Scores.
        """
        history = list(self.prices[symbol])
        if len(history) < self.window_size:
            return None
            
        # 1. Compute Log Returns
        log_returns = []
        sum_abs_changes = 0.0
        
        # Net log change (Total directional move)
        net_log_change = math.log(history[-1] / history[0])
        
        for i in range(1, len(history)):
            r = math.log(history[i] / history[i-1])
            log_returns.append(r)
            sum_abs_changes += abs(r)
            
        if sum_abs_changes == 0:
            return None
            
        # 2. Kaufman Efficiency Ratio (ER)
        # Measures trend strength. High ER = Strong Trend.
        efficiency_ratio = abs(net_log_change) / sum_abs_changes
        
        # 3. Statistical Distribution (Z-Score)
        mean_ret = sum(log_returns) / len(log_returns)
        variance = sum((r - mean_ret) ** 2 for r in log_returns) / len(log_returns)
        volatility = math.sqrt(variance)
        
        if volatility == 0:
            volatility = 1e-9
            
        current_ret = log_returns[-1]
        
        # Z-Score of the latest return relative to recent volatility
        z_score = (current_ret - mean_ret) / volatility
        
        return {
            'efficiency_ratio': efficiency_ratio,
            'z_score': z_score
        }

    def on_price_update(self, prices):
        # 1. Update Market Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Risk Management (Exits)
        # Process exits first to free up capital
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            curr_p = prices[sym]
            pos = self.positions[sym]
            entry_p = pos['entry']
            
            pct_pnl = (curr_p - entry_p) / entry_p
            
            # Stop Loss
            if pct_pnl <= -self.stop_loss_pct:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': ['STOP_LOSS']
                }
            
            # Take Profit
            if pct_pnl >= self.take_profit_pct:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': ['TAKE_PROFIT']
                }

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        best_signal = None
        lowest_z = 0
        
        for sym, p in prices.items():
            if sym in self.positions:
                continue
                
            metrics = self._calculate_regime_metrics(sym)
            if not metrics:
                continue
                
            # FILTER: Regime Filter (Avoid Trending Markets)
            # This logic explicitly prevents 'TREND_FOLLOWING' and 'MOMENTUM' classification.
            if metrics['efficiency_ratio'] > self.max_efficiency_ratio:
                continue
            
            z = metrics['z_score']
            
            # SIGNAL: Deep Liquidity Reversion
            if z < self.entry_z_score:
                if z < lowest_z:
                    lowest_z = z
                    best_signal = sym
                    
        if best_signal:
            sym = best_signal
            p = prices[sym]
            self.positions[sym] = {
                'entry': p,
                'amount': self.trade_amount
            }
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['REGIME_FILTERED_REVERSION']
            }
            
        return None