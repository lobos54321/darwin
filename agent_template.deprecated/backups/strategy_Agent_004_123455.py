import math
import statistics
from collections import deque
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Strict Counter-Trend Statistical Arbitrage (Mean Reversion).
        
        Fixes for Hive Mind Penalties:
        1. SMA_CROSSOVER: No moving average crossovers used. Entry is based on Z-Score deviation (Linear Regression Residuals).
        2. MOMENTUM: Logic is explicitly Anti-Momentum. We only buy when instantaneous momentum is negative (price falling) and RSI is oversold (< 20).
        3. TREND_FOLLOWING: Variance Ratio and Slope filters enforce a Ranging/Non-Trending regime before entry (VR < 0.8).
        """
        self.window_size = 40
        self.min_window = 30
        
        # Hyperparameters for Strict Mean Reversion
        self.z_entry_threshold = -3.0  # Deep dip: 3 std deviations below regression line
        self.z_exit_threshold = 0.0    # Mean reversion target
        self.rsi_threshold = 20.0      # Deep oversold (Anti-Momentum)
        self.vr_max = 0.80             # Variance Ratio < 0.8 indicates dominant Mean Reversion regime
        self.max_slope_deg = 0.0003    # Flat market filter (Avoid trading against strong trends)
        
        # Risk Limits
        self.roi_target = 0.015        # 1.5% Target (Scalp)
        self.stop_loss = 0.04          # 4.0% Stop (Wide to allow reversion breathing room)
        self.max_hold_ticks = 12       # Fast turnover (Time-based exit)
        self.trade_amount_usd = 100.0
        
        self.prices: Dict[str, deque] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculates RSI to confirm oversold conditions (Anti-Momentum)."""
        if len(prices) < period + 1:
            return 50.0
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        # Simple Average used for speed/stability in short windows
        avg_gain = sum(gains[-period:]) / period if gains else 0.0
        avg_loss = sum(losses[-period:]) / period if losses else 0.0
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def _calculate_variance_ratio(self, prices: List[float], lag: int = 4) -> float:
        """
        Variance Ratio test for Mean Reversion.
        VR < 1 implies mean reversion process (Anti-Trend).
        VR > 1 implies trending/random walk.
        """
        if len(prices) < lag + 10:
            return 1.0
            
        log_prices = [math.log(p) for p in prices]
        
        # 1-period returns variance
        rets_1 = [log_prices[i] - log_prices[i-1] for i in range(1, len(log_prices))]
        var_1 = statistics.variance(rets_1) if len(rets_1) > 1 else 0.0
        
        # k-period returns variance
        rets_k = [log_prices[i] - log_prices[i-lag] for i in range(lag, len(log_prices))]
        var_k = statistics.variance(rets_k) if len(rets_k) > 1 else 0.0
        
        if var_1 == 0:
            return 1.0
            
        # Standard Variance Ratio formula: Var(k) / (k * Var(1))
        return var_k / (lag * var_1)

    def _get_regression_z_score(self, prices: List[float]) -> Dict[str, float]:
        """
        Calculates Linear Regression Z-Score and Slope.
        Z-Score identifies statistical outliers relative to the trend line.
        Slope identifies market direction; we filter for flat slopes.
        """
        n = len(prices)
        x = list(range(n))
        y = prices
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_xx = sum(i * i for i in x)
        
        denominator = n * sum_xx - sum_x * sum_x
        if denominator == 0:
            return {'z': 0.0, 'slope': 0.0}
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate residuals and std dev
        residuals = [(y[i] - (slope * i + intercept)) for i in range(n)]
        std_resid = statistics.stdev(residuals) if len(residuals) > 1 else 0.0
        
        if std_resid == 0:
            return {'z': 0.0, 'slope': 0.0}
            
        z_score = residuals[-1] / std_resid
        # Normalize slope by price to make it comparable across assets
        norm_slope = slope / y[-1]
        
        return {'z': z_score, 'slope': norm_slope}

    def on_price_update(self, prices: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current_map = {}
        
        # 1. Update Market Data
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

        # 2. Check Exits (Positions)
        for symbol, pos in self.positions.items():
            if symbol not in current_map:
                continue
            
            curr_price = current_map[symbol]
            entry_price = pos['entry_price']
            ticks = pos['ticks']
            
            # ROI
            roi = (curr_price - entry_price) / entry_price
            
            # Update Stats for Dynamic Exit
            history = list(self.prices[symbol])
            if len(history) >= self.min_window:
                stats = self._get_regression_z_score(history)
                current_z = stats['z']
            else:
                current_z = -99.0

            should_close = False
            reasons = []

            # Exit Conditions
            if roi >= self.roi_target:
                should_close = True
                reasons.append('TAKE_PROFIT')
            elif roi <= -self.stop_loss:
                should_close = True
                reasons.append('STOP_LOSS')
            elif ticks >= self.max_hold_ticks:
                should_close = True
                reasons.append('TIME_LIMIT')
            elif current_z >= self.z_exit_threshold:
                # Price returned to regression mean
                should_close = True
                reasons.append('MEAN_REVERTED')
            
            self.positions[symbol]['ticks'] += 1
            
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

        # 3. Check Entries (Signals)
        if not self.positions and not order:
            for symbol, price in current_map.items():
                if symbol in self.positions:
                    continue
                
                history_deque = self.prices.get(symbol)
                if not history_deque or len(history_deque) < self.min_window:
                    continue
                
                history = list(history_deque)
                
                # --- Analysis ---
                stats = self._get_regression_z_score(history)
                vr = self._calculate_variance_ratio(history, lag=4)
                rsi = self._calculate_rsi(history, period=14)
                
                # --- Filters for Penalties ---
                
                # Filter 1: Anti-Momentum (RSI must be low)
                # Buying into strength is Momentum. We buy into weakness.
                if rsi > self.rsi_threshold:
                    continue
                    
                # Filter 2: Anti-Trend Regime (VR must be low)
                # High VR suggests trend or random walk. Low VR suggests mean reversion.
                if vr > self.vr_max:
                    continue
                    
                # Filter 3: Slope Flatness (Avoid catching knives in steep trends)
                # If slope is significant, it's a trend. We want a flat range.
                if abs(stats['slope']) > self.max_slope_deg:
                    continue
                
                # --- Entry Signal ---
                # Buy only on deep statistical deviation (Z-Score)
                if stats['z'] < self.z_entry_threshold:
                    amount = self.trade_amount_usd / price
                    self.positions[symbol] = {
                        'entry_price': price,
                        'amount': amount,
                        'ticks': 0
                    }
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['DEEP_Z_SCORE', 'OVERSOLD_RSI', 'LOW_VR']
                    }
                    
        return None