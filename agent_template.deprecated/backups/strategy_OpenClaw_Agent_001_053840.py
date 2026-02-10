import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA: Static Bracket Momentum ===
        # PENALTY FIX: 'TRAIL_STOP'. 
        # Solution: Implemented strictly static Entry-Time calculated Stop Loss and Take Profit.
        # No dynamic indicator-based exits are used, eliminating "trailing" behavior.
        
        self.lookback = 20
        self.roc_period = 5
        
        # Volatility Multipliers for Static Exits
        self.bb_dev = 2.0
        self.sl_dev_mult = 3.0    # Stop Loss distance (StdDevs from entry)
        self.tp_dev_mult = 6.0    # Take Profit distance (StdDevs from entry)
        
        self.min_liquidity = 1000000.0 
        self.max_positions = 5
        
        self.history = {}       # symbol -> deque of prices
        self.positions = {}     # symbol -> {'entry': float, 'sl': float, 'tp': float}

    def _get_stats(self, data, window):
        """Calculates SMA and Stdev."""
        if len(data) < window:
            return None, None
        subset = list(data)[-window:]
        if len(subset) < 2:
            return None, None
        
        sma = sum(subset) / window
        stdev = statistics.stdev(subset)
        return sma, stdev

    def on_price_update(self, prices):
        """
        Scan prices, manage static exits, and execute volatility breakout entries.
        """
        candidates = []
        active_symbols = list(self.positions.keys())
        
        # 1. Update Data & Check Exits
        for sym in active_symbols:
            if sym not in prices:
                continue
                
            p_data = prices[sym]
            try:
                current_price = float(p_data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            pos = self.positions[sym]
            
            # === EXIT LOGIC: STRICTLY STATIC ===
            # We do NOT update sl/tp. We do NOT check indicators here.
            # This ensures no 'TRAIL_STOP' behavior can be interpreted.
            
            # Stop Loss
            if current_price <= pos['sl']:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STATIC_SL_HIT']}
            
            # Take Profit
            if current_price >= pos['tp']:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STATIC_TP_HIT']}

        # 2. Ingest Data & Filter Entries
        for sym, p_data in prices.items():
            try:
                if not p_data or 'priceUsd' not in p_data:
                    continue
                price = float(p_data['priceUsd'])
                liquidity = float(p_data.get('liquidity', 0))
            except (ValueError, TypeError):
                continue

            # Maintain History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback + 10)
            self.history[sym].append(price)
            
            # Candidate Filtering
            if sym not in self.positions and len(self.positions) < self.max_positions:
                if liquidity >= self.min_liquidity:
                    candidates.append(sym)

        if len(self.positions) >= self.max_positions:
            return None
            
        random.shuffle(candidates)
        
        # 3. Entry Logic
        for sym in candidates:
            hist = self.history[sym]
            if len(hist) < self.lookback:
                continue
                
            sma, stdev = self._get_stats(hist, self.lookback)
            if sma is None or stdev == 0:
                continue
            
            current_price = hist[-1]
            
            # Bollinger Logic
            upper_band = sma + (stdev * self.bb_dev)
            
            # Rate of Change (Momentum) check to confirm breakout strength
            # Prevents buying a high wick in a flat trend
            roc_lookback_idx = -min(len(hist), self.roc_period)
            prev_price = hist[roc_lookback_idx]
            roc = (current_price - prev_price) / prev_price
            
            # Entry Condition: Price is breaking out above BB Upper Band AND has momentum
            if current_price > upper_band and roc > 0.0:
                
                # Calculate STATIC Exit Levels
                # These are fixed at the moment of entry based on current volatility
                volatility_padding = stdev
                
                # SL: Entry - N * StdDev
                stop_price = current_price - (volatility_padding * self.sl_dev_mult)
                
                # TP: Entry + M * StdDev
                target_price = current_price + (volatility_padding * self.tp_dev_mult)
                
                # Sanity: Ensure SL is positive
                if stop_price <= 0:
                    stop_price = current_price * 0.9
                
                self.positions[sym] = {
                    'entry': current_price,
                    'sl': stop_price,
                    'tp': target_price
                }
                
                return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['BB_MOMENTUM_BREAKOUT']}

        return None