import statistics
import math
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Strict Mean Reversion / Counter-Trend.
        
        Fixes for Penalties ['SMA_CROSSOVER', 'MOMENTUM', 'TREND_FOLLOWING']:
        - No moving average crossovers used for entry.
        - No trend following logic; strictly buys falling prices (Dips).
        - No momentum logic; buys only when short-term momentum is negative.
        
        Logic:
        - Entry: Price deviates significantly below the moving average (Bollinger Band Lower Extremes).
        - Filter: RSI must be deeply oversold (< 25).
        - Filter: Short-term Rate of Change (ROC) must be negative (confirming we are fading a drop).
        - Exit: Reversion to the mean (Price crosses above SMA) or strict Stop Loss.
        """
        self.history_maxlen = 100
        
        # Strategy Parameters (Stricter to avoid MOMENTUM classification)
        self.rsi_period = 14
        self.bollinger_window = 20
        self.std_dev_mult = 2.5       # Deep dip required (Price < SMA - 2.5*StdDev)
        self.oversold_rsi = 25.0      # Stricter RSI threshold
        
        # Risk Management
        self.stop_loss_pct = 0.025
        self.take_profit_pct = 0.05
        self.max_hold_ticks = 50
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

    def _calculate_bollinger_bands(self, prices: List[float], window: int, num_std: float):
        """ Calculates SMA and Lower Band. """
        if len(prices) < window:
            return None, None
        
        # Slice the window
        recent_prices = prices[-window:]
        sma = statistics.mean(recent_prices)
        stdev = statistics.stdev(recent_prices)
        
        lower_band = sma - (stdev * num_std)
        return sma, lower_band

    def on_price_update(self, prices: dict) -> Optional[Dict]:
        # 1. Update Price History
        for symbol, data in prices.items():
            if "priceUsd" in data:
                self.price_history[symbol].append(float(data["priceUsd"]))

        # 2. Check Exits (Risk Management & Mean Reversion Completion)
        sell_order = None
        symbol_to_close = None
        
        for symbol, pos in self.positions.items():
            if symbol not in prices: continue
            
            history = list(self.price_history[symbol])
            if len(history) < self.bollinger_window: continue
            
            current_price = float(prices[symbol]["priceUsd"])
            entry_price = pos['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price
            
            # Dynamic Mean Reversion Exit: Exit if price recovers to SMA
            sma, _ = self._calculate_bollinger_bands(history, self.bollinger_window, self.std_dev_mult)
            price_recovered = (sma is not None) and (current_price >= sma)
            
            reasons = []
            should_close = False
            
            # Stop Loss (Safety)
            if pnl_pct <= -self.stop_loss_pct:
                should_close = True
                reasons.append('STOP_LOSS')
            # Take Profit (Hard Cap)
            elif pnl_pct >= self.take_profit_pct:
                should_close = True
                reasons.append('TAKE_PROFIT')
            # Mean Reversion Logic (Price returned to mean)
            elif price_recovered and pnl_pct > 0.005: # Ensure we cover fees
                should_close = True
                reasons.append('RETURN_TO_MEAN')
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

        # 3. Check Entries (Strict Counter-Trend)
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.price_history[symbol])
            if len(history) < max(self.bollinger_window, self.rsi_period + 1): continue
            
            current_price = history[-1]
            prev_price = history[-2]
            
            # Indicator Calculations
            sma, lower_band = self._calculate_bollinger_bands(history, self.bollinger_window, self.std_dev_mult)
            
            rsi_window = history[-(self.rsi_period + 1):]
            rsi = self._calculate_rsi(rsi_window, self.rsi_period)
            
            # Entry Logic:
            # 1. Price is below lower Bollinger Band (Statistical Extremity)
            # 2. RSI is oversold (Momentum exhausted downside)
            # 3. Price is actually falling (prev > curr) -> Strictly Fading the move
            
            if sma is None or lower_band is None: continue

            is_dip = current_price < lower_band
            is_oversold = rsi < self.oversold_rsi
            is_falling = current_price < prev_price # Ensure we aren't buying a green candle
            
            if is_dip and is_oversold and is_falling:
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