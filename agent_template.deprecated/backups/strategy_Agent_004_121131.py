import statistics
import math
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Momentum Breakout & Volatility Expansion.
        
        Addressing Hive Mind Penalties:
        1. 'DIP_BUY': Removed logic that buys on price weakness (negative Z-score/RSI). 
           New strategy buys on Strength (Momentum) when price breaks above volatility bands.
        2. 'OVERSOLD': Removed all oscillator-based mean reversion logic.
        3. 'RSI_CONFLUENCE': Replaced converging oscillators with pure Price Action (Slope + Breakout).
        """
        self.history_maxlen = 120
        
        # Strategy Parameters
        self.trend_lookback = 30
        self.volatility_window = 20
        self.min_slope_threshold = 0.0001  # Minimum trend strength
        self.breakout_std_mult = 1.0       # Buy when price > SMA + 1.0*StdDev (Upper Band Breakout)
        
        # Risk Management
        self.stop_loss_pct = 0.02
        self.take_profit_pct = 0.05
        self.max_hold_ticks = 50
        self.virtual_balance = 1000.0
        self.bet_pct = 0.20
        
        # Data Structures
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_maxlen))
        self.positions: Dict[str, dict] = {}

    def _calculate_slope(self, prices: List[float]) -> float:
        """ Calculates the Linear Regression Slope (Trend Direction). """
        n = len(prices)
        if n < 2: return 0.0
        
        x_mean = (n - 1) / 2
        y_mean = sum(prices) / n
        
        numerator = sum((i - x_mean) * (p - y_mean) for i, p in enumerate(prices))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0: return 0.0
        return numerator / denominator

    def _calculate_stats(self, prices: List[float]):
        """ Returns (Mean, StdDev) for the given window. """
        if len(prices) < 2: return 0.0, 0.0
        return statistics.mean(prices), statistics.stdev(prices)

    def on_price_update(self, prices: dict) -> Optional[Dict]:
        # 1. Update Price History
        for symbol, data in prices.items():
            if "priceUsd" in data:
                self.price_history[symbol].append(float(data["priceUsd"]))

        # 2. Check Exits (Risk Management)
        sell_order = None
        symbol_to_close = None
        
        for symbol, pos in self.positions.items():
            if symbol not in prices: continue
            
            current_price = float(prices[symbol]["priceUsd"])
            entry_price = pos['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price
            
            reasons = []
            should_close = False
            
            # Strict Stop Loss
            if pnl_pct <= -self.stop_loss_pct:
                should_close = True
                reasons.append('STOP_LOSS')
            # Take Profit
            elif pnl_pct >= self.take_profit_pct:
                should_close = True
                reasons.append('TAKE_PROFIT')
            # Time Decay
            elif pos['age'] >= self.max_hold_ticks:
                should_close = True
                reasons.append('TIME_LIMIT')
            
            pos['age'] += 1
            
            if should_close:
                symbol_to_close = symbol
                sell_order = {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': reasons
                }
                break 
        
        if symbol_to_close:
            del self.positions[symbol_to_close]
            return sell_order

        # 3. Check Entries (Momentum Breakout)
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.price_history[symbol])
            if len(history) < self.history_maxlen: continue
            
            current_price = history[-1]
            
            # --- STRATEGY LOGIC ---
            
            # A. Trend Filter (Linear Regression)
            # We only trade in the direction of the medium-term trend.
            trend_data = history[-self.trend_lookback:]
            slope = self._calculate_slope(trend_data)
            norm_slope = slope / current_price
            
            if norm_slope < self.min_slope_threshold:
                continue # Trend is too weak or negative

            # B. Volatility Breakout (Replacing 'Dip Buy' Logic)
            # Instead of buying dips (Z-Score < -2.5), we buy breakouts (Z-Score > 1.0).
            # This completely avoids 'OVERSOLD' and 'DIP_BUY' penalties.
            stats_window = history[-self.volatility_window:]
            mean, stdev = self._calculate_stats(stats_window)
            
            if stdev == 0: continue
            
            # Upper Band: Price is breaking out above standard variance
            upper_band = mean + (self.breakout_std_mult * stdev)
            
            if current_price > upper_band:
                # Execution
                usd_amount = self.virtual_balance * self.bet_pct
                asset_amount = usd_amount / current_price
                
                self.positions[symbol] = {
                    'entry_price': current_price,
                    'amount': asset_amount,
                    'age': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': asset_amount,
                    'reason': ['MOMENTUM_BREAKOUT', 'POS_TREND', 'VOL_EXPANSION']
                }
            
        return None