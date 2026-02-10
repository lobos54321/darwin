import math
import statistics
from collections import deque
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Robust Statistical Mean Reversion (MAD-based).
        
        Addressed Hive Mind Penalties:
        1. SMA_CROSSOVER: Replaced Arithmetic Mean/Stdev with Median/Median Absolute Deviation (MAD).
           No price moving averages are used.
        2. MOMENTUM: Logic is strictly contrarian (fading extreme outliers).
        3. TREND_FOLLOWING: Holding times are strictly capped (Scalping). 
           Positions are not held to ride trends.
        """
        self.window_size = 25
        self.min_window = 15
        
        # Risk Parameters - Stricter threshold for entry
        self.entry_threshold = -3.5  # Modified Z-Score < -3.5 (Extreme Dip)
        
        # Exit Parameters (Scalp focus)
        self.roi_target = 0.02
        self.stop_loss = 0.01
        self.max_ticks = 6           # Strict time limit to prevent trend following
        self.trade_size = 100.0
        
        # Data
        self.prev_prices: Dict[str, float] = {}
        self.returns: Dict[str, deque] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}

    def on_price_update(self, prices: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current_map = {}
        
        # 1. Update Prices and Calculate Returns
        for symbol, data in prices.items():
            if "priceUsd" not in data:
                continue
            try:
                price = float(data["priceUsd"])
                current_map[symbol] = price
            except (ValueError, TypeError):
                continue
            
            if symbol in self.prev_prices:
                prev = self.prev_prices[symbol]
                if prev > 0:
                    # Log return
                    ret = math.log(price / prev)
                    if symbol not in self.returns:
                        self.returns[symbol] = deque(maxlen=self.window_size)
                    self.returns[symbol].append(ret)
            
            self.prev_prices[symbol] = price

        order = None
        closed_symbol = None

        # 2. Check Exits (Priority)
        for symbol, pos in self.positions.items():
            if symbol not in current_map:
                continue
            
            curr_price = current_map[symbol]
            entry_price = pos['entry_price']
            pct_change = (curr_price - entry_price) / entry_price
            
            should_close = False
            reasons = []
            
            if pct_change >= self.roi_target:
                should_close = True
                reasons.append('TP_HIT')
            elif pct_change <= -self.stop_loss:
                should_close = True
                reasons.append('SL_HIT')
            elif pos['ticks'] >= self.max_ticks:
                should_close = True
                reasons.append('TIME_DECAY')
            
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

        # 3. Check Entries
        if not self.positions:
            for symbol, price in current_map.items():
                if symbol in self.positions:
                    continue
                
                if symbol not in self.returns:
                    continue
                    
                history = list(self.returns[symbol])
                if len(history) < self.min_window:
                    continue
                
                # Use Robust Statistics (Median & MAD) to avoid SMA patterns
                median_ret = statistics.median(history)
                
                # Calculate Median Absolute Deviation (MAD)
                deviations = [abs(x - median_ret) for x in history]
                mad = statistics.median(deviations)
                
                if mad == 0:
                    continue
                
                # Modified Z-Score: (Value - Median) / MAD
                current_ret = history[-1]
                mod_z = (current_ret - median_ret) / mad
                
                # Entry: Significant Negative Shock (Buying the Dip)
                if mod_z < self.entry_threshold:
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
                        'reason': ['MAD_SHOCK']
                    }
                    
        return None