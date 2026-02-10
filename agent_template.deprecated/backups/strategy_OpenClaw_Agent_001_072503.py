import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        self.window_size = 20
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Filters ---
        self.min_liquidity = 6_000_000.0
        self.min_24h_change = 1.5  # Focus on assets with global daily momentum
        
        # --- Exit Management ---
        self.trailing_stop_pct = 0.012  # 1.2% Trailing Stop
        self.hard_stop_pct = 0.02       # 2.0% Hard Stop
        self.max_hold_ticks = 40        # Reduced hold time for higher frequency
        
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
            
            # Update High Water Mark for Trailing Stop
            if current_price > pos['high_water_mark']:
                pos['high_water_mark'] = current_price
            
            # Calculate metrics
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

        # Filter candidates: High Liquidity + Positive 24h Trend
        candidates = []
        for s, data in prices.items():
            if data['liquidity'] >= self.min_liquidity:
                if data['priceChange24h'] >= self.min_24h_change:
                    candidates.append(s)
        
        # Sort by strongest 24h momentum
        candidates.sort(key=lambda s: prices[s]['priceChange24h'], reverse=True)
        
        for symbol in candidates:
            if symbol in self.positions: continue
            
            history = self.history[symbol]
            if len(history) < self.window_size:
                continue

            # --- Logic: Donchian Channel Breakout ---
            # To strictly avoid 'DIP_BUY', we only buy if the current price
            # is higher than the MAXIMUM price of the previous N ticks.
            # This ensures we are buying strength/breakouts, never dips.
            
            prev_prices = list(history)[:-1]
            current_price = history[-1]
            
            local_high = max(prev_prices)
            local_low = min(prev_prices)
            
            # Condition 1: Strict Breakout
            if current_price <= local_high:
                continue
                
            # Condition 2: Minimum Volatility Check
            # Ensure the channel isn't flat (avoiding fake breakouts in dead markets)
            channel_width = (local_high - local_low) / local_low
            if channel_width < 0.001: # 0.1% minimum volatility required
                continue

            # Execute Trade
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
                'reason': ['DONCHIAN_BREAKOUT']
            }
            
        return None