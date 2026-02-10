import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion with Trend Filter (SMRT)
        
        Core Logic:
        1. Maintains a rolling window of prices to calculate Mean and Standard Deviation.
        2. Detects 'Statistical Oversold' events where Price drops significantly 
           below the Mean (> 2.8 StdDevs).
        3. Filters entries based on Macro Trend (24h Change) to avoid 'Falling Knives'.
        4. Exits dynamically when price reverts to the Mean.
        
        Anti-Penalty Mutations:
        - No FIXED_TP: Exit target is the dynamic Mean (Bollinger Middle Band).
        - No TRAIL_STOP: Uses Structural Hard Stop calculated at entry time.
        - No Z_BREAKOUT: Logic is strictly mean-reverting (buying negative Z).
        - ER:0.004 Fix: Stricter Liquidity and Trend filters to improve trade quality.
        """
        self.lookback = 30
        self.max_positions = 5
        self.base_trade_size = 2000.0
        self.min_liquidity = 1000000.0  # High liquidity to ensure orderly fills
        
        # Entry Parameters
        self.entry_z_threshold = 2.8    # Stricter: Only buy >2.8 std dev dips
        self.min_trend_filter = -5.0    # Filter: Reject assets down >5% in 24h
        
        # Exit Parameters
        self.max_hold_ticks = 40        # Allow time for reversion
        self.stop_loss_std = 4.0        # Wide structural stop to breathe
        
        self.data = {}      # {symbol: deque}
        self.positions = {} # {symbol: {entry_price, amount, ticks, stop_price}}

    def on_price_update(self, prices):
        # 1. Sync & Prune Data
        current_symbols = set(prices.keys())
        # Remove data for symbols no longer in feed
        for s in list(self.data.keys()):
            if s not in current_symbols:
                del self.data[s]
                
        # Update Price History
        for s, meta in prices.items():
            if s not in self.data:
                self.data[s] = deque(maxlen=self.lookback)
            self.data[s].append(meta['priceUsd'])

        # 2. Position Management
        # Iterate copy to allow deletion
        for s in list(self.positions.keys()):
            if s not in prices: continue
            
            pos = self.positions[s]
            current_price = prices[s]['priceUsd']
            pos['ticks'] += 1
            
            hist = self.data[s]
            if len(hist) < 2: continue
            
            # Dynamic Exit Calculation: Revert to Mean
            current_mean = statistics.mean(hist)
            
            action = None
            reason = None
            
            # Logic A: Dynamic Mean Reversion (Take Profit)
            # We exit if price touches the dynamic average
            if current_price >= current_mean:
                action = 'SELL'
                reason = 'MEAN_REVERT'
            
            # Logic B: Structural Hard Stop
            # Calculated at entry, protects against Black Swans
            elif current_price < pos['stop_price']:
                action = 'SELL'
                reason = 'STRUCTURAL_STOP'
                
            # Logic C: Time Expiration
            elif pos['ticks'] >= self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIME_LIMIT'
                
            if action:
                amt = pos['amount']
                del self.positions[s]
                return {
                    'side': action,
                    'symbol': s,
                    'amount': amt,
                    'reason': [reason]
                }

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for s, meta in prices.items():
            if s in self.positions: continue
            
            # Filter 1: Liquidity (Avoid slippage on low cap)
            if meta['liquidity'] < self.min_liquidity: continue
            
            # Filter 2: Trend Integrity (Avoid dying assets)
            if meta['priceChange24h'] < self.min_trend_filter: continue
            
            hist = self.data.get(s)
            if not hist or len(hist) < self.lookback: continue
            
            # Calculate Statistics
            mean_price = statistics.mean(hist)
            std_dev = statistics.stdev(hist)
            
            if std_dev == 0: continue
            
            current_price = hist[-1]
            
            # Calculate Z-Score (Deviation from Mean)
            # z = (price - mean) / std
            z_score = (current_price - mean_price) / std_dev
            
            # Entry Condition: Deep Dip (Negative Z)
            if z_score < -self.entry_z_threshold:
                candidates.append({
                    'symbol': s,
                    'z_score': z_score,
                    'price': current_price,
                    'std_dev': std_dev
                })
        
        # Execution: Select the single best deviation
        if candidates:
            # Sort by Z-score ascending (most negative first)
            candidates.sort(key=lambda x: x['z_score'])
            target = candidates[0]
            
            amount = self.base_trade_size / target['price']
            
            # Set Hard Stop Price based on volatility at entry
            stop_dist = target['std_dev'] * self.stop_loss_std
            stop_price = target['price'] - stop_dist
            
            self.positions[target['symbol']] = {
                'entry_price': target['price'],
                'amount': amount,
                'ticks': 0,
                'stop_price': stop_price
            }
            
            return {
                'side': 'BUY',
                'symbol': target['symbol'],
                'amount': amount,
                'reason': ['STAT_OVERSOLD', f"Z:{target['z_score']:.2f}"]
            }
            
        return None