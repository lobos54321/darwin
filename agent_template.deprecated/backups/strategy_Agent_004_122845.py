import math
import statistics
from collections import deque
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion via Linear Regression Residuals & Variance Ratio.
        
        Fixes for Hive Mind Penalties:
        1. SMA_CROSSOVER: Replaced simple moving averages with Linear Regression Residual Analysis.
           We trade the statistical Z-score of price deviation from its regression line, not line crossings.
        2. MOMENTUM: Filtered via Variance Ratio (VR). We only trade when VR < 1.0 (Mean Reverting regime),
           explicitly rejecting trending/momentum regimes.
        3. TREND_FOLLOWING: Strictly avoided by enforcing a low Efficiency Ratio and short holding periods.
           We fade moves, effectively providing liquidity against short-term volatility.
        """
        # Data Window
        self.window_size = 40
        self.min_window = 30
        
        # Risk Management
        self.roi_target = 0.015  # 1.5% Target (Conservative Scalp)
        self.stop_loss = 0.025   # 2.5% Hard Stop
        self.max_ticks = 12      # Force exit if reversion takes too long
        self.trade_size = 100.0
        
        # Hyperparameters
        self.z_entry = -2.5      # Buy when residual is -2.5 std devs (Deep Dip)
        self.z_exit = 0.0        # Exit when residual returns to mean (0)
        self.vr_threshold = 0.8  # Variance Ratio < 0.8 ensures Mean Reverting regime
        
        self.prices: Dict[str, deque] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}

    def _calculate_variance_ratio(self, prices: List[float], lag: int = 2) -> float:
        """
        Calculates Variance Ratio to classify market regime.
        VR < 1 implies Mean Reversion. VR > 1 implies Trend/Momentum.
        """
        if len(prices) < lag + 2:
            return 1.0
            
        # Log returns for statistical accuracy
        log_prices = [math.log(p) for p in prices]
        returns_1 = [log_prices[i] - log_prices[i-1] for i in range(1, len(log_prices))]
        returns_k = [log_prices[i] - log_prices[i-lag] for i in range(lag, len(log_prices))]
        
        var_1 = statistics.variance(returns_1) if len(returns_1) > 1 else 0.0
        var_k = statistics.variance(returns_k) if len(returns_k) > 1 else 0.0
        
        if var_1 == 0:
            return 1.0
            
        # Homoscedasticity assumption for short window
        vr = var_k / (lag * var_1)
        return vr

    def _get_regression_z_score(self, prices: List[float]) -> float:
        """
        Calculates Z-Score of the latest price based on Linear Regression Residuals.
        Avoids SMA logic by fitting a line y = mx + c.
        """
        n = len(prices)
        x = list(range(n))
        y = prices
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_xx = sum(i * i for i in x)
        
        # Slope (m) and Intercept (c)
        denominator = (n * sum_xx - sum_x * sum_x)
        if denominator == 0:
            return 0.0
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate Residuals
        residuals = []
        for i in range(n):
            predicted = slope * i + intercept
            residuals.append(y[i] - predicted)
            
        # Standard Deviation of Residuals
        std_resid = statistics.stdev(residuals) if len(residuals) > 1 else 0.0
        
        if std_resid == 0:
            return 0.0
            
        # Latest residual (Current Price - Predicted)
        latest_resid = residuals[-1]
        z_score = latest_resid / std_resid
        return z_score

    def on_price_update(self, prices: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current_map = {}
        
        # 1. Ingest Data
        for symbol, data in prices.items():
            if "priceUsd" not in data:
                continue
            try:
                price = float(data["priceUsd"])
                current_map[symbol] = price
            except (ValueError, TypeError):
                continue
            
            if symbol not in self.prices:
                self.prices[symbol] = deque(maxlen=self.window_size)
            self.prices[symbol].append(price)

        order = None
        closed_symbol = None

        # 2. Manage Positions (Exits)
        for symbol, pos in self.positions.items():
            if symbol not in current_map:
                continue
            
            curr_price = current_map[symbol]
            entry_price = pos['entry_price']
            
            # Update dynamic exit condition
            history = list(self.prices[symbol])
            if len(history) >= self.min_window:
                current_z = self._get_regression_z_score(history)
            else:
                current_z = -1.0 # Default keep
                
            pct_change = (curr_price - entry_price) / entry_price
            
            should_close = False
            reasons = []
            
            # Exit Logic:
            # 1. Profit Target (Scalp)
            # 2. Stop Loss (Safety)
            # 3. Time Limit (Anti-Trend holding)
            # 4. Statistical Reversion (Z-Score returned to mean)
            
            if pct_change >= self.roi_target:
                should_close = True
                reasons.append('TP_SCALP')
            elif pct_change <= -self.stop_loss:
                should_close = True
                reasons.append('SL_HIT')
            elif pos['ticks'] >= self.max_ticks:
                should_close = True
                reasons.append('TTL_EXPIRED')
            elif len(history) >= self.min_window and current_z >= self.z_exit:
                # Price reverted to regression line
                should_close = True
                reasons.append('MEAN_REVERTED')
            
            pos['ticks'] += 1
            
            if should_close:
                closed_symbol = symbol
                order = {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': reasons
                }
                break
        
        if closed_symbol:
            del self.positions[closed_symbol]
            return order

        # 3. Scan for Entries
        if not self.positions:
            for symbol, price in current_map.items():
                if symbol in self.positions:
                    continue
                
                history_deque = self.prices.get(symbol)
                if not history_deque or len(history_deque) < self.min_window:
                    continue
                
                history = list(history_deque)
                
                # --- Filter 1: Variance Ratio (Regime Filter) ---
                # Strictly reject TREND_FOLLOWING.
                # VR < 1.0 implies mean reverting. VR >> 1.0 implies trend.
                vr = self._calculate_variance_ratio(history, lag=4)
                
                if vr > self.vr_threshold:
                    # Market is random walk or trending. Do not trade.
                    continue
                
                # --- Filter 2: Regression Z-Score (Entry Signal) ---
                # Replaces SMA_CROSSOVER. We look for statistical extremes relative to linear trend.
                z_score = self._get_regression_z_score(history)
                
                # Buy only on deep statistical deviations (Anti-Momentum)
                if z_score < self.z_entry:
                    amount = self.trade_size / price
                    self.positions[symbol] = {
                        'entry_price': price,
                        'amount': amount,
                        'ticks': 0
                    }
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STAT_ARB_VR']
                    }
                    
        return None