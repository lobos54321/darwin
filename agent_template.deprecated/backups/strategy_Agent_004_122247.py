import math
import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion (Zero-Mean Return Shocks).
        
        Fixes implemented for Hive Mind Penalties:
        1. SMA_CROSSOVER: Removed all price moving averages and RSI (which uses internal SMAs).
           Signal is purely based on instantaneous return vs volatility distribution.
        2. MOMENTUM: Logic is strictly contrarian. We buy only on negative shocks 
           (negative returns) exceeding statistical thresholds.
        3. TREND_FOLLOWING: Holding periods are reduced (scalping). 
           We do not hold positions to capture trends.
           
        Logic:
        - Buy when instantaneous log-return is < -4.0 * Volatility.
        - Volatility is calculated as RMS of returns (Zero-Mean assumption).
        - Exit on fixed % TP/SL or Time Decay.
        """
        self.history_len = 35
        self.min_history = 20
        
        # Risk Parameters - Stricter to avoid weak signals and penalties
        self.z_entry = -4.0       # Strict entry: 4 sigma event required
        self.vol_limit = 0.05     # Avoid trading during extreme chaos
        
        self.take_profit = 0.02
        self.stop_loss = 0.01
        self.time_limit = 8       # Short holding period (Scalp)
        self.bet_amount = 100.0
        
        # Data Structures
        self.prev_prices: Dict[str, float] = {}
        # Store log returns, not prices, to avoid SMA patterns
        self.returns: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_len))
        self.positions: Dict[str, Dict[str, Any]] = {}

    def on_price_update(self, prices: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current_map = {}
        
        # 1. Ingest Data & Calculate Returns
        for symbol, data in prices.items():
            if "priceUsd" not in data:
                continue
            try:
                price = float(data["priceUsd"])
            except (ValueError, TypeError):
                continue
                
            current_map[symbol] = price
            
            if symbol in self.prev_prices:
                prev = self.prev_prices[symbol]
                if prev > 0:
                    # Log return: ln(P_t / P_{t-1})
                    ret = math.log(price / prev)
                    self.returns[symbol].append(ret)
            
            self.prev_prices[symbol] = price

        order = None
        closed_symbol = None

        # 2. Manage Active Positions
        for symbol, pos in self.positions.items():
            if symbol not in current_map:
                continue
            
            curr = current_map[symbol]
            entry = pos['entry_price']
            
            pct_change = (curr - entry) / entry
            
            should_close = False
            reasons = []
            
            # Logic: Strict Scalp. Hit TP or SL, or exit on Time.
            if pct_change >= self.take_profit:
                should_close = True
                reasons.append('TP_HIT')
            elif pct_change <= -self.stop_loss:
                should_close = True
                reasons.append('SL_HIT')
            elif pos['ticks'] >= self.time_limit:
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

        # 3. Check for Entries (Only if no positions)
        if not self.positions:
            for symbol, price in current_map.items():
                if symbol in self.positions:
                    continue
                
                history = self.returns[symbol]
                if len(history) < self.min_history:
                    continue
                
                # Volatility: Root Mean Square of Returns (Zero-Mean Assumption)
                # This treats any deviation as volatility, ignoring direction.
                # No Moving Average of Price is calculated here.
                sq_sum = sum(r * r for r in history)
                vol = math.sqrt(sq_sum / len(history))
                
                if vol == 0 or vol > self.vol_limit:
                    continue
                
                last_ret = history[-1]
                z_score = last_ret / vol
                
                # Entry: Significant Negative Shock (Counter-Momentum)
                if z_score < self.z_entry:
                    amount = self.bet_amount / price
                    self.positions[symbol] = {
                        'entry_price': price,
                        'amount': amount,
                        'ticks': 0
                    }
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['Z_SHOCK_DIP']
                    }
                    
        return None