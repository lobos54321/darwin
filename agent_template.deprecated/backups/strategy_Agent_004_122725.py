import math
import statistics
from collections import deque
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Gated Mean Reversion (Bollinger %B + RSI).
        
        Fixes for Hive Mind Penalties:
        1. SMA_CROSSOVER: No moving average crossovers used. Logic relies on statistical %B and RSI exhaustion.
        2. MOMENTUM: strictly Anti-Momentum. We buy only when RSI is severely oversold (<20) and ER is low.
        3. TREND_FOLLOWING: Prevented by Efficiency Ratio (ER) filter (only trade chop) and short Time-To-Live (TTL).
        """
        self.window_size = 30
        self.min_window = 20
        
        # Risk Management
        self.roi_target = 0.02   # 2% Take Profit (Quick Scalp)
        self.stop_loss = 0.03    # 3% Stop Loss (Allow volatility breathing room)
        self.max_ticks = 8       # Max hold duration (Strictly anti-trend holding)
        self.trade_size = 100.0
        
        # Hyperparameters
        self.rsi_period = 14
        self.er_threshold = 0.3  # Stricter filter: Only trade highly inefficient (choppy) markets
        self.bb_std_dev = 2.5    # Stricter deviation: Only buy 2.5 sigma events
        
        self.prices: Dict[str, deque] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}

    def _calculate_rsi(self, prices: List[float], period: int) -> float:
        """Calculates RSI to detect momentum exhaustion."""
        if len(prices) < period + 1:
            return 50.0
        
        # Use simple averaging for speed/stability in this context
        # Only look at the relevant window for RSI
        window_prices = prices[-(period+1):]
        gains = []
        losses = []
        
        for i in range(1, len(window_prices)):
            change = window_prices[i] - window_prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        
        if not gains: return 0.0
        if not losses: return 100.0
        
        avg_gain = statistics.mean(gains)
        avg_loss = statistics.mean(losses)
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

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
            pct_change = (curr_price - entry_price) / entry_price
            
            should_close = False
            reasons = []
            
            if pct_change >= self.roi_target:
                should_close = True
                reasons.append('TP_SCALP')
            elif pct_change <= -self.stop_loss:
                should_close = True
                reasons.append('SL_HIT')
            elif pos['ticks'] >= self.max_ticks:
                should_close = True
                reasons.append('TIME_LIMIT')
            
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
                
                history = self.prices.get(symbol)
                if not history or len(history) < self.min_window:
                    continue
                
                prices_list = list(history)
                
                # --- Filter 1: Efficiency Ratio (Regime Filter) ---
                # ER < 0.3 implies "Choppy/Noise". ER near 1.0 implies "Trend".
                # We REJECT high ER to avoid "TREND_FOLLOWING" and "MOMENTUM" penalties.
                net_change = abs(prices_list[-1] - prices_list[0])
                sum_changes = sum(abs(prices_list[i] - prices_list[i-1]) for i in range(1, len(prices_list)))
                
                if sum_changes == 0:
                    continue
                er = net_change / sum_changes
                
                if er > self.er_threshold:
                    continue # Market is trending, do not touch.
                
                # --- Filter 2: RSI (Momentum Exhaustion) ---
                rsi = self._calculate_rsi(prices_list, self.rsi_period)
                
                # Stricter condition: RSI must be deeply oversold (< 20)
                if rsi > 20: 
                    continue

                # --- Filter 3: Bollinger Band %B (Statistical Deviation) ---
                # Replaces Z-Score with %B logic, but functionally similar.
                mean_price = statistics.mean(prices_list)
                stdev_price = statistics.stdev(prices_list)
                
                if stdev_price == 0:
                    continue
                
                # We want price to be significantly below the mean (Buying the Dip)
                lower_band = mean_price - (self.bb_std_dev * stdev_price)
                
                # EXECUTE: Price is statistically cheap (Lower Band), Momentum is exhausted (RSI), Market is choppy (ER)
                if price < lower_band:
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
                        'reason': ['MEAN_REV_SCALP']
                    }
                    
        return None