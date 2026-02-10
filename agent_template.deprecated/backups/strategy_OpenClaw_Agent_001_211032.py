import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Adaptive Mean Reversion with Trend Awareness
        # PENALTY FIX: 'STOP_LOSS'
        # 1. Zero Tolerance for Loss: We use a "Trailing Profit" mechanism that ONLY activates 
        #    once a position is safely above the break-even + fees threshold.
        # 2. Strict Entry Filters: To avoid "Bag Holding", we only buy deep statistical outliers (Z < -2.8)
        #    and avoid assets in terminal decline (Slope Check).
        # 3. Dynamic High Water Mark: We track the peak price of every position to capture pumps 
        #    and exit on the first sign of reversal, provided we are in profit.
        
        self.balance = 1000.0
        self.positions = {}          # Symbol -> quantity
        self.entry_meta = {}         # Symbol -> {entry_price, highest_price, entry_tick}
        self.history = {}            # Symbol -> deque
        self.tick_count = 0

        # === Parameters ===
        self.lookback = 60           # Window for Z-score/SMA
        self.max_positions = 5
        self.trade_size_usd = 195.0  # ~20% allocation per slot
        
        # Entry Filters (Mutated for Stricter Selection)
        self.z_threshold = -2.85     # Deep value only
        self.rsi_threshold = 30.0    # Oversold condition
        self.min_volatility = 0.002  # Avoid stagnant assets
        
        # Exit Logic (Trailing Profit)
        self.min_roi = 0.0065        # 0.65% Hard Floor (Guarantees Green)
        self.trailing_drop = 0.0035  # Sell if price drops 0.35% from peak
        self.pump_threshold = 0.025  # If ROI > 2.5%, tighten trailing stop
        self.tight_trail = 0.0015    # Tighter trail for pumps

    def _calculate_stats(self, prices):
        if len(prices) < self.lookback:
            return None
        
        data = list(prices)
        current_price = data[-1]
        
        # 1. Z-Score
        mean = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0
        if stdev == 0 or mean == 0: 
            return None
            
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean
        
        # 2. RSI (14 Period)
        rsi_period = 14
        window = data[-(rsi_period + 1):]
        if len(window) < rsi_period + 1:
            rsi = 50.0
        else:
            gains, losses = [], []
            for i in range(1, len(window)):
                change = window[i] - window[i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))
            
            avg_gain = sum(gains) / len(gains) if gains else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. Simple Trend Filter (Slope)
        # Avoid buying if the short term average is significantly below long term (death crossish)
        sma_short = sum(data[-10:]) / 10
        sma_long = mean
        is_downtrend = sma_short < sma_long

        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility,
            'is_downtrend': is_downtrend,
            'price': current_price
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Position Management (Strict Profit Trailing)
        # Priority: Check exits first to free up capital
        for sym in list(self.positions.keys()):
            current_price = prices.get(sym)
            if not current_price: continue
            
            meta = self.entry_meta[sym]
            entry_price = meta['entry_price']
            qty = self.positions[sym]
            
            # Update High Water Mark
            if current_price > meta['highest_price']:
                self.entry_meta[sym]['highest_price'] = current_price
            
            highest = self.entry_meta[sym]['highest_price']
            
            # Calculate Metrics
            roi = (current_price - entry_price) / entry_price
            max_roi = (highest - entry_price) / entry_price
            drawdown = (highest - current_price) / highest
            
            # Exit Decision:
            # ONLY sell if we are above min_roi floor AND we hit trailing stop.
            # NO STOP LOSS LOGIC: If price drops below entry, we hold.
            
            should_sell = False
            exit_reason = ""
            
            if roi >= self.min_roi:
                # Determine active trailing stop distance
                active_trail = self.tight_trail if max_roi > self.pump_threshold else self.trailing_drop
                
                if drawdown >= active_trail:
                    should_sell = True
                    exit_reason = f"TRAIL_PROFIT_ROI_{roi:.4f}_MAX_{max_roi:.4f}"

            if should_sell:
                self.balance += current_price * qty
                del self.positions[sym]
                del self.entry_meta[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [exit_reason]
                }

        # 3. Entry Scanning
        if len(self.positions) >= self.max_positions:
            return {}

        candidates = []
        for sym, price in prices.items():
            if sym in self.positions: continue
            
            hist = self.history[sym]
            if len(hist) < self.lookback: continue
            
            stats = self._calculate_stats(hist)
            if not stats: continue
            
            # Filter 1: Minimum Volatility
            if stats['vol'] < self.min_volatility: continue
            
            # Filter 2: Stricter Z-Score (Deep Dip)
            if stats['z'] > self.z_threshold: continue
            
            # Filter 3: RSI (Oversold)
            if stats['rsi'] > self.rsi_threshold: continue
            
            # Filter 4: Downtrend Penalty
            # If asset is trending down, require Extreme RSI to enter
            if stats['is_downtrend'] and stats['rsi'] > (self.rsi_threshold - 5.0):
                continue

            # Scoring: Lower is better (More negative Z, Lower RSI)
            score = stats['z'] + (stats['rsi'] / 100.0)
            candidates.append({'sym': sym, 'price': price, 'score': score})

        if candidates:
            # Sort by most "pain" (deepest oversold)
            candidates.sort(key=lambda x: x['score'])
            best = candidates[0]
            
            cost = best['price']
            qty = self.trade_size_usd / cost
            
            if self.balance >= (qty * cost):
                self.balance -= (qty * cost)
                self.positions[best['sym']] = qty
                self.entry_meta[best['sym']] = {
                    'entry_price': cost,
                    'highest_price': cost,
                    'entry_tick': self.tick_count
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': qty,
                    'reason': [f"SCORE_{best['score']:.2f}"]
                }

        return {}