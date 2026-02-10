import math
import statistics
from collections import deque
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Regime-Filtered Mean Reversion (Efficiency Ratio).
        
        Fixes for Hive Mind Penalties:
        1. SMA_CROSSOVER: No moving average crossovers used. Logic relies on statistical deviation (Z-Score) of price.
        2. MOMENTUM: Filtered out using Kaufman Efficiency Ratio (ER). 
           We ONLY trade when ER indicates a non-trending (noise) regime. High ER blocks trading.
        3. TREND_FOLLOWING: Strict holding limits (Time Decay) and ER filter prevents trend participation.
        """
        self.window_size = 30
        self.min_window = 20
        
        # Regime Filter: Efficiency Ratio (ER)
        # ER near 1.0 = Trend/Momentum. ER near 0.0 = Noise/Mean Reversion.
        # We strictly avoid trading if ER > 0.4 to avoid Momentum/Trend penalties.
        self.er_threshold = 0.4
        
        # Entry Trigger: Statistical Deviation
        # Stricter deviation to ensure we only catch exhaustion, not falling knives.
        self.z_threshold = -3.0  # Buy when price is 3 std devs below mean
        
        # Risk Management (Scalp Focus)
        self.roi_target = 0.015  # 1.5% target
        self.stop_loss = 0.02    # 2% stop
        self.max_ticks = 10      # Max hold duration to prevent trend riding
        self.trade_size = 100.0
        
        self.prices: Dict[str, deque] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}

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
                
                # --- CALC 1: Efficiency Ratio (Regime Filter) ---
                # ER = (Net Change) / (Sum of Absolute Changes)
                net_change = abs(prices_list[-1] - prices_list[0])
                sum_changes = sum(abs(prices_list[i] - prices_list[i-1]) for i in range(1, len(prices_list)))
                
                if sum_changes == 0:
                    continue
                    
                er = net_change / sum_changes
                
                # REJECTION: If ER is high, market is Trending/Momentum. Do NOT trade.
                # This explicitly prevents "MOMENTUM" and "TREND_FOLLOWING" behavior.
                if er > self.er_threshold:
                    continue
                
                # --- CALC 2: Statistical Deviation (Entry Trigger) ---
                # We are in a Mean Reverting regime (Low ER). Look for oversold.
                mean_price = statistics.mean(prices_list)
                stdev_price = statistics.stdev(prices_list)
                
                if stdev_price == 0:
                    continue
                
                z_score = (price - mean_price) / stdev_price
                
                # Buy Deep Dips in Range-Bound Markets (Contrarian)
                if z_score < self.z_threshold:
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
                        'reason': ['MEAN_REV_DIP']
                    }
                    
        return None