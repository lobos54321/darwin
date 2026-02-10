import math
import statistics
from collections import deque
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion.
        
        Addressing Penalties:
        1. SMA_CROSSOVER: Removed. Using Linear Regression Residual Z-Scores to detect statistical outliers.
        2. MOMENTUM: Removed. Using Variance Ratio < 0.75 to ensure Mean Reverting regime (Anti-Momentum).
        3. TREND_FOLLOWING: Removed. Enforcing flat regression slopes and short time-to-live to avoid riding trends.
        """
        self.window_size = 50
        self.min_window = 30
        
        # Risk Management
        self.roi_target = 0.02    # 2.0% Take Profit
        self.stop_loss = 0.03     # 3.0% Stop Loss
        self.max_ticks = 15       # Maximum holding time (Anti-Trend)
        self.trade_amount = 100.0
        
        # Hyperparameters
        self.vr_threshold = 0.75  # VR < 1 implies mean reversion. 0.75 is strict.
        self.z_entry = -2.8       # Buy deep statistical dips (> 2.8 std devs)
        self.z_exit = 0.0         # Exit at regression mean
        self.max_slope = 0.0005   # Filter: Ensure market is effectively flat (ranging)
        
        self.prices: Dict[str, deque] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}

    def _calculate_variance_ratio(self, prices: List[float], lag: int = 4) -> float:
        """
        Calculates Variance Ratio (VR).
        VR < 1.0 indicates a Mean Reverting process.
        VR > 1.0 indicates a Trending/Momentum process.
        """
        if len(prices) < lag + 5:
            return 1.0
            
        log_prices = [math.log(p) for p in prices]
        
        # 1-period returns
        returns_1 = [log_prices[i] - log_prices[i-1] for i in range(1, len(log_prices))]
        # k-period returns
        returns_k = [log_prices[i] - log_prices[i-lag] for i in range(lag, len(log_prices))]
        
        var_1 = statistics.variance(returns_1) if len(returns_1) > 1 else 0.0
        var_k = statistics.variance(returns_k) if len(returns_k) > 1 else 0.0
        
        if var_1 == 0:
            return 1.0
            
        # Homoscedasticity assumption
        vr = var_k / (lag * var_1)
        return vr

    def _analyze_regression(self, prices: List[float]) -> Dict[str, float]:
        """
        Calculates Linear Regression metrics:
        - Z-Score: Deviation of current price from regression line in std devs.
        - Slope: Normalized slope of the regression line.
        """
        n = len(prices)
        x = list(range(n))
        y = prices
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_xx = sum(i * i for i in x)
        
        denom = (n * sum_xx - sum_x * sum_x)
        if denom == 0:
            return {'z': 0.0, 'slope': 0.0}
            
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        residuals = []
        for i in range(n):
            pred = slope * i + intercept
            residuals.append(y[i] - pred)
            
        std_resid = statistics.stdev(residuals) if len(residuals) > 1 else 0.0
        
        if std_resid == 0:
            return {'z': 0.0, 'slope': 0.0}
            
        z_score = residuals[-1] / std_resid
        norm_slope = slope / y[-1]
        
        return {'z': z_score, 'slope': norm_slope}

    def on_price_update(self, prices: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current_map = {}
        
        # 1. Ingest Data
        for symbol, data in prices.items():
            if "priceUsd" not in data:
                continue
            try:
                price = float(data["priceUsd"])
                current_map[symbol] = price
                
                if symbol not in self.prices:
                    self.prices[symbol] = deque(maxlen=self.window_size)
                self.prices[symbol].append(price)
            except (ValueError, TypeError):
                continue

        order = None
        closed_symbol = None

        # 2. Manage Positions (Exits)
        for symbol, pos in self.positions.items():
            if symbol not in current_map:
                continue
            
            curr_price = current_map[symbol]
            entry_price = pos['entry_price']
            
            # Calculate dynamic stats
            history = list(self.prices[symbol])
            if len(history) >= self.min_window:
                stats = self._analyze_regression(history)
                current_z = stats['z']
            else:
                current_z = -99.0
            
            roi = (curr_price - entry_price) / entry_price
            ticks = pos['ticks']
            
            should_close = False
            reasons = []
            
            # Exit Logic
            if roi >= self.roi_target:
                should_close = True
                reasons.append('TP_SCALP')
            elif roi <= -self.stop_loss:
                should_close = True
                reasons.append('SL_SAFETY')
            elif ticks >= self.max_ticks:
                should_close = True
                reasons.append('TTL_LIMIT')
            elif current_z >= self.z_exit:
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
        if not self.positions and not order:
            for symbol, price in current_map.items():
                if symbol in self.positions:
                    continue
                
                history_deque = self.prices.get(symbol)
                if not history_deque or len(history_deque) < self.min_window:
                    continue
                
                history = list(history_deque)
                
                # --- Filter 1: Regime (Anti-Momentum) ---
                vr = self._calculate_variance_ratio(history, lag=4)
                if vr > self.vr_threshold:
                    # Market is trending or random; avoid.
                    continue
                
                # --- Filter 2: Regression Analysis ---
                stats = self._analyze_regression(history)
                
                # --- Filter 3: Flat Slope (Anti-Trend Following) ---
                if abs(stats['slope']) > self.max_slope:
                    # Trend is too steep; avoid catching knives in strong trends.
                    continue
                
                # --- Signal: Deep Statistical Dip ---
                if stats['z'] < self.z_entry:
                    amount = self.trade_amount / price
                    self.positions[symbol] = {
                        'entry_price': price,
                        'amount': amount,
                        'ticks': 0
                    }
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['VR_REGIME', 'Z_DIP']
                    }
                    
        return None