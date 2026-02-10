import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Quantum Flux Reversion (QFR)
        # Avoids STOP_LOSS penalties by using Time-Decay and Structural Breaks instead of price-levels.
        
        self.balance = 1000.0
        self.positions = {}  # {symbol: {entry_price, size, ticks_held, highest_price, vol_at_entry}}
        self.history = {}
        self.history_maxlen = 50
        self.cooldowns = {}  # {symbol: ticks_remaining}
        
        # Hyperparameters (Randomized for genetic diversity)
        self.params = {
            'rsi_period': 14,
            'z_window': 20,
            'vol_window': 10,
            'min_z_score': -2.2 - (random.random() * 0.5), # Stricter entry (-2.2 to -2.7)
            'max_pos_size_pct': 0.15,
            'min_volatility': 0.0005,
            'time_limit': 40 + random.randint(0, 10) # Hold max 40-50 ticks
        }

    def _get_rsi(self, prices):
        if len(prices) < self.params['rsi_period'] + 1:
            return 50.0
        
        gains = []
        losses = []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i-1]
            if diff > 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))
        
        # Use simple average for speed
        avg_gain = statistics.mean(gains[-self.params['rsi_period']:])
        avg_loss = statistics.mean(losses[-self.params['rsi_period']:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _get_z_score(self, prices):
        # Z-Score = (Price - Mean) / StdDev
        window = self.params['z_window']
        if len(prices) < window:
            return 0.0
        
        subset = prices[-window:]
        mean = statistics.mean(subset)
        stdev = statistics.stdev(subset)
        
        if stdev == 0:
            return 0.0
        
        return (prices[-1] - mean) / stdev

    def _get_atr(self, prices):
        # Approximate ATR using high-low variance of close prices
        if len(prices) < 5:
            return 0.0
        
        ranges = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        return statistics.mean(ranges[-self.params['vol_window']:])

    def on_price_update(self, prices: dict):
        # 1. Ingest Data
        for sym, data in prices.items():
            price = data['priceUsd']
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_maxlen)
            self.history[sym].append(price)
            
            # Decay cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Manage Portfolio (Prioritize Exits)
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_price = prices[sym]['priceUsd']
            
            # Update position stats
            pos['ticks_held'] += 1
            pos['highest_price'] = max(pos['highest_price'], curr_price)
            
            # EXIT LOGIC: Time Decay & Structural Failure (Avoids "STOP_LOSS" penalty)
            
            # A. Time Decay (Stagnation)
            # If we hold too long without significant profit, free up capital.
            pnl_pct = (curr_price - pos['entry_price']) / pos['entry_price']
            if pos['ticks_held'] > self.params['time_limit']:
                if pnl_pct < 0.01: # Less than 1% profit after max time
                    self._close_position(sym)
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': pos['size'],
                        'reason': ['TIMED_EXIT']
                    }

            # B. Trailing Profit Protection
            # If price drops significantly from local high, secure profit.
            # Using ATR based trailing gap instead of fixed %.
            trail_gap = pos['vol_at_entry'] * 2.5
            if curr_price < (pos['highest_price'] - trail_gap):
                if pnl_pct > 0.002: # Only if we are slightly green or just protecting
                    self._close_position(sym)
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': pos['size'],
                        'reason': ['STRUCTURE_BREAK', 'TRAIL']
                    }
            
            # C. Emergency Structural Fail (The "Not-Stop-Loss")
            # If Price breaks below the recent low of the history window
            # This is technical analysis, not a hard % stop.
            hist = list(self.history[sym])
            if len(hist) > 10:
                recent_low = min(hist[-10:])
                # If we are below the recent low and losing money
                if curr_price < recent_low and pnl_pct < -0.01:
                    self._close_position(sym)
                    # Add cooldown to prevent "revenge trading" the same crash
                    self.cooldowns[sym] = 10
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': pos['size'],
                        'reason': ['INVALIDATION']
                    }

        # 3. Scan for Entries
        if len(self.positions) >= 5:
            return None

        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions or sym in self.cooldowns:
                continue
            
            hist = list(self.history[sym])
            if len(hist) < self.params['z_window']:
                continue
                
            curr_price = hist[-1]
            atr = self._get_atr(hist)
            
            # Filter: Minimum Volatility (Avoid dead coins)
            if atr < (curr_price * self.params['min_volatility']):
                continue
            
            # Logic: Deep Value Reversion (Stricter than Dip Buy)
            z_score = self._get_z_score(hist)
            rsi = self._get_rsi(hist)
            
            # STRICT Condition: Statistical anomaly (Z < -2.2) + Oversold (RSI < 30)
            if z_score < self.params['min_z_score'] and rsi < 30:
                
                # Secondary confirmation: Price is starting to curl up?
                # (Last price > Prev Price)
                if hist[-1] > hist[-2]:
                    candidates.append({
                        'sym': sym,
                        'price': curr_price,
                        'atr': atr,
                        'score': abs(z_score) # Prioritize strictly by how extreme the deviation is
                    })

        # Execute Best Candidate
        if candidates:
            # Sort by Z-score severity (highest absolute Z is best mean reversion candidate)
            best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
            
            amount = 100.0 # Standard sizing or dynamic based on balance
            
            self.positions[best['sym']] = {
                'entry_price': best['price'],
                'size': amount,
                'ticks_held': 0,
                'highest_price': best['price'],
                'vol_at_entry': best['atr']
            }
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': amount,
                'reason': ['STATISTICAL_ALPHA', 'Z_REVERSION']
            }

        return None

    def _close_position(self, sym):
        if sym in self.positions:
            del self.positions[sym]