import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        self.window_size = 30
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Filters ---
        self.min_liquidity = 5_000_000.0
        
        # --- Entry Thresholds ---
        # High Z-Score indicates a breakout above the mean (Momentum)
        # We explicitly avoid DIP_BUY by ensuring Z-Score is POSITIVE and high.
        # We avoid KELTNER by using pure statistical Standard Deviation logic (Bollinger-style).
        self.z_score_threshold = 2.1
        
        # --- Exit Management ---
        self.trailing_stop_pct = 0.015  # 1.5% Trailing Stop
        self.hard_stop_pct = 0.025      # 2.5% Hard Stop
        self.max_hold_ticks = 45        # Fast rotation

        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Prune State
        current_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in current_symbols:
                del self.history[s]

        # 2. Update Price History
        for s, data in prices.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.window_size)
            self.history[s].append(data['priceUsd'])

        # 3. Manage Existing Positions
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # Update High Water Mark
            if current_price > pos['high_water_mark']:
                pos['high_water_mark'] = current_price
            
            hwm = pos['high_water_mark']
            entry_price = pos['entry_price']
            
            drawdown = (current_price - hwm) / hwm
            pnl = (current_price - entry_price) / entry_price
            
            exit_reason = None
            
            if drawdown <= -self.trailing_stop_pct:
                exit_reason = 'TRAILING_STOP'
            elif pnl <= -self.hard_stop_pct:
                exit_reason = 'HARD_STOP'
            elif self.tick_count - pos['entry_tick'] >= self.max_hold_ticks:
                exit_reason = 'TIMEOUT'
            
            if exit_reason:
                amount = pos['amount']
                del self.positions[symbol]
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': amount, 
                    'reason': [exit_reason]
                }

        # 4. New Entry Scan
        if len(self.positions) >= self.max_positions:
            return None

        # Filter candidates based on liquidity and basic trend alignment
        candidates = []
        for s, data in prices.items():
            if data['liquidity'] >= self.min_liquidity:
                # Only look at assets with positive 24h change (Trend Alignment)
                if data['priceChange24h'] > 0.0: 
                    candidates.append(s)
        
        # Sort by Volume to find high activity breakouts (Momentum)
        candidates.sort(key=lambda s: prices[s]['volume24h'], reverse=True)
        
        for symbol in candidates:
            if symbol in self.positions: continue
            
            history = self.history[symbol]
            if len(history) < self.window_size:
                continue

            prices_list = list(history)
            current_price = prices_list[-1]
            
            # --- Statistical Calculations ---
            mean_price = sum(prices_list) / len(prices_list)
            
            # Variance & StdDev
            variance = sum((x - mean_price) ** 2 for x in prices_list) / len(prices_list)
            std_dev = math.sqrt(variance)
            
            if std_dev == 0: continue
            
            # Z-Score Calculation: (Price - Mean) / StdDev
            z_score = (current_price - mean_price) / std_dev
            
            # --- Strategy Logic: Statistical Momentum Breakout ---
            # 1. Z-Score Breakout: Price is > N std devs above mean.
            #    High POSITIVE z-score = Strong Upward Momentum (Anti-Dip)
            if z_score > self.z_score_threshold:
                
                # 2. Acceleration Check:
                #    Ensure the most recent candle is higher than the previous one
                #    to confirm immediate buying pressure.
                prev_price = prices_list[-2]
                if current_price > prev_price:
                    
                    amount = self.trade_size_usd / current_price
                    self.positions[symbol] = {
                        'entry_price': current_price,
                        'high_water_mark': current_price,
                        'amount': amount,
                        'entry_tick': self.tick_count
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['Z_SCORE_BREAKOUT']
                    }
            
        return None