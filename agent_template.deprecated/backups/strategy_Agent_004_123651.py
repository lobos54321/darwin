import math
import statistics
from collections import deque
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: High-Conviction Statistical Arbitrage.
        
        Adjustments for Hive Mind Penalties:
        1. 'TEST_TRADE': Fixed by enforcing stricter Z-Score (-3.2) and RSI (15) thresholds.
           We only enter when statistical probability of reversion is extremely high.
        2. 'OPENCLAW_VERIFY': Fixed by tightening the Variance Ratio (0.7) and increasing window size.
           This ensures we only trade in robust Mean Reversion regimes, filtering out 'fake' dips.
        """
        self.window_size = 50          # Increased from 40 for better statistical weight
        self.min_window = 40           # Strict data requirement
        
        # Stricter Hyperparameters
        self.z_entry_threshold = -3.2  # Deeper discount required (was -3.0)
        self.z_exit_threshold = 0.0    # Revert to regression mean
        self.rsi_threshold = 15.0      # Extreme oversold only (was 20.0)
        self.vr_max = 0.70             # Strong Mean Reversion regime required (was 0.8)
        self.max_slope_deg = 0.0002    # Flatter market required (was 0.0003)
        
        # Risk Limits
        self.roi_target = 0.02         # 2.0% Target (Higher conviction trade)
        self.stop_loss = 0.05          # 5.0% Stop (Wider stop for deep volatility)
        self.max_hold_ticks = 20       # Increased time limit to allow reversion
        self.trade_amount_usd = 100.0
        
        self.prices: Dict[str, deque] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        if not gains and not losses:
            return 50.0
            
        # Using simple average for stability
        avg_gain = sum(gains[-period:]) / period if gains else 0.0
        avg_loss = sum(losses[-period:]) / period if losses else 0.0
        
        if avg_loss == 0:
            return 100.0
        if avg_gain == 0:
            return 0.0
            
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def _calculate_variance_ratio(self, prices: List[float], lag: int = 8) -> float:
        """
        Calculates Variance Ratio with a longer lag (8) to ensure regime stability.
        VR < 1.0 implies mean reverting.
        """
        if len(prices) < lag + 10:
            return 1.0
            
        log_prices = [math.log(p) if p > 0 else 0 for p in prices]
        
        # 1-period returns variance
        rets_1 = [log_prices[i] - log_prices[i-1] for i in range(1, len(log_prices))]
        var_1 = statistics.variance(rets_1) if len(rets_1) > 1 else 0.0
        
        # k-period returns variance
        rets_k = [log_prices[i] - log_prices[i-lag] for i in range(lag, len(log_prices))]
        var_k = statistics.variance(rets_k) if len(rets_k) > 1 else 0.0
        
        if var_1 <= 1e-9:
            return 1.0
            
        return var_k / (lag * var_1)

    def _get_regression_stats(self, prices: List[float]) -> Dict[str, float]:
        n = len(prices)
        if n < 2:
            return {'z': 0.0, 'slope': 0.0}
            
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
        
        residuals = [(y[i] - (slope * i + intercept)) for i in range(n)]
        std_resid = statistics.stdev(residuals) if len(residuals) > 1 else 0.0
        
        if std_resid == 0:
            return {'z': 0.0, 'slope': 0.0}
            
        z_score = residuals[-1] / std_resid
        norm_slope = slope / y[-1] if y[-1] != 0 else 0.0
        
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

        # 2. Manage Exits
        for symbol, pos in self.positions.items():
            if symbol not in current_map:
                continue
            
            curr_price = current_map[symbol]
            entry_price = pos['entry_price']
            ticks = pos['ticks']
            
            roi = (curr_price - entry_price) / entry_price
            
            history = list(self.prices[symbol])
            if len(history) >= self.min_window:
                stats = self._get_regression_stats(history)
                current_z = stats['z']
            else:
                current_z = -99.0

            should_close = False
            reasons = []

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

        # 3. Evaluate Entries
        if not self.positions and not order:
            best_candidate = None
            lowest_z = 0.0

            for symbol, price in current_map.items():
                if symbol in self.positions:
                    continue
                
                history_deque = self.prices.get(symbol)
                if not history_deque or len(history_deque) < self.min_window:
                    continue
                
                history = list(history_deque)
                
                # --- Strict Filter Logic ---
                stats = self._get_regression_stats(history)
                z_score = stats['z']
                
                # 1. Statistical Outlier Check
                if z_score >= self.z_entry_threshold:
                    continue
                    
                # 2. Trend Slope Check (Must be ranging/flat)
                if abs(stats['slope']) > self.max_slope_deg:
                    continue
                    
                # 3. Variance Ratio Check (Must be Mean Reverting Regime)
                vr = self._calculate_variance_ratio(history, lag=8)
                if vr > self.vr_max:
                    continue
                    
                # 4. Anti-Momentum Check (Must be Oversold)
                rsi = self._calculate_rsi(history, period=14)
                if rsi > self.rsi_threshold:
                    continue
                
                # Select the deepest value opportunity
                if best_candidate is None or z_score < lowest_z:
                    lowest_z = z_score
                    amount = self.trade_amount_usd / price
                    best_candidate = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STRICT_Z', 'LOW_VR', 'OVERSOLD']
                    }
            
            if best_candidate:
                self.positions[best_candidate['symbol']] = {
                    'entry_price': current_map[best_candidate['symbol']],
                    'amount': best_candidate['amount'],
                    'ticks': 0
                }
                return best_candidate
                    
        return None