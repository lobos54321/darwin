import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.window_size = 50
        self.min_liquidity = 10000000.0
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # EMA parameters (40 periods)
        self.ema_period = 40
        self.alpha = 2 / (self.ema_period + 1)
        
        # Logic Thresholds - Stricter to fix Z:-3.93 penalty
        self.z_entry_threshold = -2.6    # Start looking for dips here
        self.z_panic_floor = -4.5        # Stop looking here (crash protection)
        self.rsi_threshold = 25          # Deep oversold required
        self.ema_slope_threshold = -0.0002 # Stability Gate: Reject if EMA is crashing
        self.min_volatility = 0.003      # 0.3% Min Volatility
        
        # Exit parameters
        self.stop_loss_pct = 0.04
        self.max_hold_ticks = 30
        
        self.history = {}
        self.positions = {}
        self.tick_count = 0

    def calculate_indicators(self, symbol, current_price):
        if symbol not in self.history or len(self.history[symbol]) < self.window_size:
            return None
            
        prices = list(self.history[symbol])
        
        # 1. Volatility (Standard Deviation)
        try:
            stdev = statistics.stdev(prices)
        except:
            return None
            
        if stdev == 0:
            return None

        # 2. EMA & Slope Calculation
        # We reconstruct the EMA trace to ensure consistency and get the previous tick's EMA
        # to measure the slope (rate of change) of the baseline.
        ema = prices[0]
        ema_prev = prices[0]
        
        for i, p in enumerate(prices):
            # Store the EMA value before the current update to calculate slope later
            if i > 0:
                ema_prev = ema
            ema = (p * self.alpha) + (ema * (1 - self.alpha))
            
        # Slope: Percentage change of the EMA itself
        slope = (ema - ema_prev) / ema_prev if ema_prev > 0 else 0
        
        # 3. Z-Score (Distance from EMA in standard deviations)
        z_score = (current_price - ema) / stdev
        
        # 4. RSI (Relative Strength Index)
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        if not deltas:
            return None
            
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        avg_gain = sum(gains) / len(deltas)
        avg_loss = sum(losses) / len(deltas)
        
        if avg_loss == 0:
            rsi = 100
        elif avg_gain == 0:
            rsi = 0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return {
            'z': z_score,
            'rsi': rsi,
            'ema': ema,
            'slope': slope,
            'stdev': stdev
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # --- 1. Update History ---
        active_candidates = []
        for symbol, data in prices.items():
            if data['liquidity'] < self.min_liquidity:
                continue
                
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(data['priceUsd'])
            
            if len(self.history[symbol]) == self.window_size:
                active_candidates.append(symbol)
                
        # --- 2. Manage Exits ---
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            stats = self.calculate_indicators(symbol, current_price)
            
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            action = None
            reason = None
            
            # Stop Loss (Hard exit)
            if roi < -self.stop_loss_pct:
                action = 'SELL'
                reason = 'STOP_LOSS'
            
            # Timeout (Time decay exit)
            elif (self.tick_count - pos['entry_tick']) > self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIMEOUT'
            
            # Take Profit (Mean Reversion complete)
            # If price reverts to the EMA, our hypothesis is fulfilled.
            elif stats and current_price >= stats['ema']:
                action = 'SELL'
                reason = 'EMA_REVERTED'
                
            if action == 'SELL':
                amount = pos['amount']
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': [reason]
                }

        # --- 3. Manage Entries ---
        if len(self.positions) >= self.max_positions:
            return None
            
        potential_buys = []
        
        for symbol in active_candidates:
            if symbol in self.positions:
                continue
                
            current_price = prices[symbol]['priceUsd']
            stats = self.calculate_indicators(symbol, current_price)
            
            if not stats:
                continue
            
            # --- FILTER LOGIC ---
            
            # 1. Volatility Gate: Ignore dead assets
            if (stats['stdev'] / current_price) < self.min_volatility:
                continue
            
            # 2. Z-Score Window: Valid Dip
            # Must be a significant dip (<-2.6) but NOT a complete crash (>-4.5)
            if stats['z'] > self.z_entry_threshold or stats['z'] < self.z_panic_floor:
                continue
                
            # 3. Stability Gate (Fix for Falling Knife)
            # If the EMA is sloping down too fast, the "Mean" is moving away from us.
            if stats['slope'] < self.ema_slope_threshold:
                continue
                
            # 4. RSI Gate: Must be oversold
            if stats['rsi'] > self.rsi_threshold:
                continue
                
            # 5. Micro-Reversal Confirmation
            # Don't catch the knife on the way down. Wait for a green tick.
            prev_price = self.history[symbol][-2]
            if current_price <= prev_price:
                continue
            
            potential_buys.append((symbol, stats['z']))
            
        if potential_buys:
            # Sort by Z-score (deepest valid dip first)
            potential_buys.sort(key=lambda x: x[1])
            best_symbol = potential_buys[0][0]
            best_z = potential_buys[0][1]
            
            current_price = prices[best_symbol]['priceUsd']
            amount = self.trade_size_usd / current_price
            
            self.positions[best_symbol] = {
                'entry_price': current_price,
                'entry_tick': self.tick_count,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': best_symbol,
                'amount': amount,
                'reason': ['Z_DIP', f'Z:{best_z:.2f}']
            }
            
        return None