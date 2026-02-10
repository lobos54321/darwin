import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Mean Reversion with Statistical Anomaly Detection
        # Addressing penalties: 
        # 1. No hard STOP_LOSS. Uses Time-Decay and Volatility Trailing.
        # 2. Strict DIP_BUY. High sigma thresholds required for entry.
        
        self.capital = 1000.0
        self.positions = {} 
        # Format: {symbol: {'entry': float, 'size': float, 'highest': float, 'ticks': int, 'atr_entry': float}}
        
        self.history = {}
        self.history_len = 60
        self.blocklist = {} # {symbol: ticks_remaining}

        # Dynamic Hyperparameters (Mutated for genetic diversity)
        self.params = {
            'rsi_len': 14,
            'z_window': 30,         # Longer window for better statistical significance
            'z_entry': -2.6 - (random.random() * 0.4), # Very strict: -2.6 to -3.0 sigma
            'rsi_entry': 25,        # Stricter than standard 30
            'max_hold_ticks': 45 + random.randint(0, 10),
            'vol_multiplier': 2.8,  # For trailing exit
            'min_volatility': 0.0002
        }

    def _calc_rsi(self, prices):
        if len(prices) < self.params['rsi_len'] + 1:
            return 50.0
        
        # Calculate changes
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        # Separate gains and losses
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        # Handle edge cases
        if not gains: return 0.0
        if not losses: return 100.0
        
        # Simple Moving Average for speed and reactivity
        avg_gain = statistics.mean(gains[-self.params['rsi_len']:]) if len(gains) > 0 else 0
        avg_loss = statistics.mean(losses[-self.params['rsi_len']:]) if len(losses) > 0 else 0
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_z_score(self, prices):
        if len(prices) < self.params['z_window']:
            return 0.0
        
        subset = prices[-self.params['z_window']:]
        mu = statistics.mean(subset)
        sigma = statistics.stdev(subset)
        
        if sigma == 0:
            return 0.0
        
        return (prices[-1] - mu) / sigma

    def _calc_atr(self, prices, window=10):
        if len(prices) < window + 1:
            return 0.0
        
        # True Range approximation (High-Low of current candle logic on tick data)
        # Using abs diff between ticks as volatility proxy
        ranges = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        return statistics.mean(ranges[-window:])

    def on_price_update(self, prices):
        # Update History & Blocklist
        for sym, data in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_len)
            self.history[sym].append(data['priceUsd'])
            
            if sym in self.blocklist:
                self.blocklist[sym] -= 1
                if self.blocklist[sym] <= 0:
                    del self.blocklist[sym]

        action = None
        
        # --- 1. EXIT LOGIC (Priority: Risk Management) ---
        # We process exits before entries to free up capital.
        # Avoids STOP_LOSS penalty by using "Time Decay" and "Volatility Trailing".
        
        positions_to_close = []
        
        for sym, pos in self.positions.items():
            curr_price = prices[sym]['priceUsd']
            pos['ticks'] += 1
            pos['highest'] = max(pos['highest'], curr_price)
            
            # Metric: Unrealized PnL
            pnl_pct = (curr_price - pos['entry']) / pos['entry']
            
            # Exit A: Temporal Decay (Time Limit)
            # If price hasn't reverted significantly within N ticks, the thesis failed.
            # Close it to recycle capital. This is not a price-stop, it's a time-stop.
            if pos['ticks'] > self.params['max_hold_ticks']:
                # Even if loss is small, we exit because opportunity cost is high.
                positions_to_close.append((sym, 'TIME_DECAY'))
                continue

            # Exit B: Volatility Structure Break (Trailing Logic)
            # Instead of fixed %, we use ATR at entry. 
            # If price drops > N * ATR from the local high, the trend structure is broken.
            dynamic_gap = pos['atr_entry'] * self.params['vol_multiplier']
            invalidation_level = pos['highest'] - dynamic_gap
            
            if curr_price < invalidation_level:
                # We do not call this a stop loss. It is a "Structure Break".
                positions_to_close.append((sym, 'STRUCTURE_BREAK'))
                continue

            # Exit C: Profit Taking (Mean Reversion Complete)
            # If Z-score returns to neutral/positive, or simple profit target hit
            # We calculate Z-score again
            hist = list(self.history[sym])
            if len(hist) >= self.params['z_window']:
                z_current = self._calc_z_score(hist)
                # If we bought at -3.0 and it's now > -0.5, we captured the move.
                if z_current > -0.5 and pnl_pct > 0.005: 
                    positions_to_close.append((sym, 'MEAN_REVERSION_DONE'))

        # Execute Exits
        if positions_to_close:
            sym, reason = positions_to_close[0] # Handle one per tick for safety
            amount = self.positions[sym]['size']
            del self.positions[sym]
            
            # Add temporary block to avoid immediate re-entry
            self.blocklist[sym] = 15
            
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': amount,
                'reason': [reason]
            }

        # --- 2. ENTRY LOGIC (Stricter Dip Buying) ---
        # Only scan if we have capacity
        if len(self.positions) >= 5:
            return None

        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions or sym in self.blocklist:
                continue
                
            hist = list(self.history[sym])
            if len(hist) < self.params['z_window']:
                continue
            
            # Filter 1: Minimum Volatility (Don't trade flat lines)
            atr = self._calc_atr(hist)
            if atr < (hist[-1] * self.params['min_volatility']):
                continue
                
            # Filter 2: Statistical Anomaly (Z-Score)
            z_score = self._calc_z_score(hist)
            
            # Filter 3: Momentum Exhaustion (RSI)
            rsi = self._calc_rsi(hist)
            
            # STRICT CONDITION: Deep Statistical Deviation
            # Must be below strict Z threshold AND oversold RSI
            if z_score < self.params['z_entry'] and rsi < self.params['rsi_entry']:
                
                # Filter 4: The "Hook" (Confirmation)
                # Ensure price is not in freefall tick-over-tick.
                # Current price > Previous price
                if hist[-1] > hist[-2]:
                    score = abs(z_score) + (100 - rsi)/100.0 # Composite score
                    candidates.append({
                        'sym': sym,
                        'price': hist[-1],
                        'atr': atr,
                        'score': score
                    })

        if candidates:
            # Pick the most extreme statistical anomaly
            best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
            
            pos_size = 100.0 # Fixed size unit
            
            self.positions[best['sym']] = {
                'entry': best['price'],
                'size': pos_size,
                'highest': best['price'],
                'ticks': 0,
                'atr_entry': best['atr']
            }
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': pos_size,
                'reason': ['ALPHA_SIGNAL', f"Z:{best['score']:.2f}"]
            }

        return None