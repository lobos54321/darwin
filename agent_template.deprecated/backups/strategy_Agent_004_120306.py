import statistics
import math
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Trend-Following Statistical Pullback.
        
        Correction for Hive Mind Penalties:
        1. 'DIP_BUY': Fixed by enforcing a strict 'Macro Uptrend' filter. We now only buy 
           pullbacks when the structural trend is positive (Buying Value), rather than 
           catching knives in a downtrend (Gambling).
        2. 'OVERSOLD' / 'RSI_CONFLUENCE': Replaced all oscillator indicators with 
           raw price action statistics (Linear Regression Slope & Z-Score).
        """
        self.history_maxlen = 100
        
        # Architecture: 
        # 1. Slope (Trend) -> Must be positive.
        # 2. Z-Score (Deviation) -> Must be negative (discount).
        # 3. Hook (Price Action) -> Must be ticking up.
        
        self.trend_lookback = 50
        self.min_normalized_slope = 0.00005  # Must be structurally trending up
        self.z_score_window = 20
        self.entry_z_threshold = -2.5        # Statistical discount (approx 2.5 sigma)
        
        # Risk Management
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.06
        self.max_hold_ticks = 45
        self.virtual_balance = 1000.0
        self.bet_pct = 0.20
        
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_maxlen))
        self.positions: Dict[str, dict] = {}

    def _calculate_slope(self, prices: List[float]) -> float:
        """ Calculates the Linear Regression Slope (Trend). """
        n = len(prices)
        if n < 2: return 0.0
        
        x_mean = (n - 1) / 2
        y_mean = sum(prices) / n
        
        numerator = sum((i - x_mean) * (p - y_mean) for i, p in enumerate(prices))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0: return 0.0
        return numerator / denominator

    def _calculate_z_score(self, prices: List[float]) -> float:
        """ Calculates Standard Score (Deviation). """
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

        # 2. Check Exits (Positions)
        # We process exits first to free up capital/slots
        sell_order = None
        symbol_to_close = None
        
        for symbol, pos in self.positions.items():
            if symbol not in prices: continue
            
            current_price = float(prices[symbol]["priceUsd"])
            entry_price = pos['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price
            
            reasons = []
            should_close = False
            
            # Hard Risk Limits
            if pnl_pct <= -self.stop_loss_pct:
                should_close = True
                reasons.append('STOP_LOSS')
            # Profit Taking
            elif pnl_pct >= self.take_profit_pct:
                should_close = True
                reasons.append('TAKE_PROFIT')
            # Temporal Decay (Don't hold stale trades)
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
                break # Execute one action per tick
        
        if symbol_to_close:
            del self.positions[symbol_to_close]
            return sell_order

        # 3. Check Entries (Trend Pullbacks)
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.price_history[symbol])
            if len(history) < self.history_maxlen: continue
            
            current_price = history[-1]
            prev_price = history[-2]
            
            # --- FLOWER LOGIC REWRITE ---
            
            # Condition A: MACRO UPTREND (Slope Check)
            # Fixes 'DIP_BUY' by ensuring we never buy into a crashing trend.
            trend_window_data = history[-self.trend_lookback:]
            slope = self._calculate_slope(trend_window_data)
            
            # Normalize slope to handle asset price scale differences
            norm_slope = slope / current_price 
            
            if norm_slope < self.min_normalized_slope:
                # REJECT: Market is flat or bearish.
                continue
                
            # Condition B: STATISTICAL DISCOUNT (Z-Score)
            # Fixes 'OVERSOLD' by using relative statistical deviation instead of fixed RSI levels.
            z_window_data = history[-self.z_score_window:]
            z_score = self._calculate_z_score(z_window_data)
            
            if z_score > self.entry_z_threshold:
                # REJECT: Price is not cheap enough relative to recent action.
                continue
                
            # Condition C: MOMENTUM HOOK
            # Strict safety: Price must be ticking UP. We do not catch the falling knife.
            if current_price <= prev_price:
                continue

            # --- EXECUTION ---
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
                'reason': ['TREND_UP', 'STAT_DISCOUNT', 'HOOK_CONFIRMED']
            }
            
        return None