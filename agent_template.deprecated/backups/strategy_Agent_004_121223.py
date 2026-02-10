import statistics
import math
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Mean Reversion / Counter-Trend.
        
        Addressing Penalties: ['SMA_CROSSOVER', 'MOMENTUM', 'TREND_FOLLOWING']
        1. 'MOMENTUM' / 'TREND_FOLLOWING': Removed all logic buying on positive slope or breakout. 
           Switched to Counter-Trend (Buying weakness/dips).
        2. 'SMA_CROSSOVER': Logic relies on Statistical Z-Score and RSI extremes, not moving average crossovers.
        
        Logic:
        - Buy when price is statistically oversold (Low Z-Score) AND RSI is low.
        - Sell on recovery or strict risk limits.
        """
        self.history_maxlen = 120
        
        # Strategy Parameters
        self.rsi_period = 14
        self.z_score_window = 30
        
        # Entry Thresholds (Strict Mean Reversion)
        # Buying deep dips to avoid 'MOMENTUM' classification
        self.entry_rsi_threshold = 28.0       
        self.entry_z_score_threshold = -2.2   # Price is >2.2 StdDevs below mean
        
        # Risk Management
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.06 # Aim for a bounce
        self.max_hold_ticks = 40
        self.virtual_balance = 1000.0
        self.bet_pct = 0.20
        
        # Data Structures
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_maxlen))
        self.positions: Dict[str, dict] = {}

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """ Calculates Relative Strength Index. """
        if len(prices) < period + 1:
            return 50.0
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_deltas = deltas[-period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d < 0]
        
        if not gains and not losses: return 50.0
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_z_score(self, prices: List[float]) -> float:
        """ Calculates Z-Score (Number of Standard Deviations from Mean). """
        if len(prices) < 2: return 0.0
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        if stdev == 0: return 0.0
        return (prices[-1] - mean) / stdev

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
            
            # Stop Loss
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

        # 3. Check Entries (Mean Reversion)
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.price_history[symbol])
            if len(history) < self.z_score_window: continue
            
            current_price = history[-1]
            
            # Logic: Counter-Trend
            # We want to buy when the price has fallen too far, too fast.
            
            stats_window = history[-self.z_score_window:]
            z_score = self._calculate_z_score(stats_window)
            
            rsi_window = history[-(self.rsi_period + 1):]
            rsi = self._calculate_rsi(rsi_window, self.rsi_period)
            
            # Conditions
            is_oversold_stat = z_score < self.entry_z_score_threshold
            is_oversold_rsi = rsi < self.entry_rsi_threshold
            
            if is_oversold_stat and is_oversold_rsi:
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
                    'reason': ['MEAN_REVERSION', 'OVERSOLD', 'COUNTER_TREND']
                }
            
        return None