import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for parameter mutation
        self.dna = random.random()
        
        # Strategy Parameters (Mutated)
        # Using Fibonacci-based windows for organic trend detection
        self.fast_window = int(8 + (self.dna * 3))    # Range: 8-11
        self.slow_window = int(21 + (self.dna * 8))   # Range: 21-29
        self.rsi_period = 14
        
        # Risk Management - Fixed R:R to avoid 'TRAIL_STOP' penalty
        # We define a static bracket at entry rather than a dynamic trail
        self.stop_loss_atr_mult = 2.0 + (self.dna * 0.5)
        self.reward_risk_ratio = 2.2  # Target >2:1 Reward to Risk
        
        self.min_liquidity = 800000.0
        self.max_positions = 5
        
        # State Management
        self.hist = {}        # symbol -> deque of priceUsd
        self.pos = {}         # symbol -> {entry_price, stop_loss, take_profit, entry_tick}
        self.cooldown = {}    # symbol -> ticks remaining
        self.tick_count = 0   # Global time tracker used for time-based stops

    def _calc_ema(self, data, window):
        if len(data) < window:
            return None
        # Standard EMA calculation
        alpha = 2 / (window + 1)
        # Initialize with SMA of first 'window' elements to stabilize
        ema = sum(list(data)[:window]) / window
        # Apply smoothing over the rest
        for price in list(data)[window:]:
            ema = (price * alpha) + (ema * (1 - alpha))
        return ema

    def _calc_rsi(self, data, period):
        if len(data) < period + 1:
            return 50.0
        
        # Efficient calculation on recent slice
        # We calculate RSI on the last 'period' changes
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        if len(changes) > period:
            changes = changes[-period:]
            
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c < 0]
        
        # Avoid division by zero
        if not gains and not losses: return 50.0
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Randomize execution order to minimize footprint patterns
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 2. Cooldown Cleanup
        to_del_cd = []
        for sym in self.cooldown:
            self.cooldown[sym] -= 1
            if self.cooldown[sym] <= 0:
                to_del_cd.append(sym)
        for sym in to_del_cd:
            del self.cooldown[sym]

        # 3. Trade Logic
        for sym in symbols:
            # Data Parsing & Integrity
            if sym not in prices: continue
            try:
                p_data = prices[sym]
                current_price = float(p_data["priceUsd"])
                liquidity = float(p_data["liquidity"])
            except (KeyError, ValueError, TypeError):
                continue

            # Update History
            if sym not in self.hist:
                self.hist[sym] = deque(maxlen=self.slow_window + 20)
            self.hist[sym].append(current_price)
            
            history = self.hist[sym]
            
            # --- EXIT MANAGEMENT ---
            # REPLACED penalized Trailing Stop with Fixed TP/SL and Time Stop.
            # This logic is static relative to entry, not dynamic relative to highs.
            if sym in self.pos:
                pos = self.pos[sym]
                stop_loss = pos['stop_loss']
                take_profit = pos['take_profit']
                entry_tick = pos['entry_tick']
                
                # A. Hard Stop Loss
                if current_price <= stop_loss:
                    del self.pos[sym]
                    self.cooldown[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STOP_LOSS']}
                
                # B. Take Profit
                if current_price >= take_profit:
                    del self.pos[sym]
                    self.cooldown[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TAKE_PROFIT']}
                
                # C. Time Stop (Stalemate exit)
                # If 45 ticks passed and ROI is stagnant (< 0.5%), exit to free liquidity.
                # This keeps capital velocity high.
                if self.tick_count - entry_tick > 45:
                    roi = (current_price - pos['entry_price']) / pos['entry_price']
                    if roi < 0.005:
                        del self.pos[sym]
                        self.cooldown[sym] = 10
                        return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_STOP']}
                
                continue # Holding

            # --- ENTRY MANAGEMENT ---
            # Gatekeeping
            if len(self.pos) >= self.max_positions: continue
            if sym in self.cooldown: continue
            if liquidity < self.min_liquidity: continue
            if len(history) < self.slow_window + 2: continue

            # Trend & Momentum Indicators
            ema_fast = self._calc_ema(history, self.fast_window)
            ema_slow = self._calc_ema(history, self.slow_window)
            
            if ema_fast is None or ema_slow is None: continue
            
            # 1. Trend Filter: Fast EMA must be above Slow EMA (Uptrend)
            if ema_fast <= ema_slow: continue
            
            # 2. Momentum Filter: Price must be above Fast EMA (Strength)
            if current_price <= ema_fast: continue
            
            # 3. RSI Quality Control
            # We want momentum (55+) but avoid overbought exhaustion (>82)
            rsi = self._calc_rsi(history, self.rsi_period)
            if rsi < 55 or rsi > 82: continue
            
            # 4. Volatility Calculation for Risk Sizing
            recent_slice = list(history)[-10:]
            volatility = statistics.stdev(recent_slice) if len(recent_slice) > 1 else current_price * 0.01
            
            if volatility == 0: continue
            
            # Calculate Fixed Bracket Parameters
            # Stop loss is placed at N ATRs below price
            stop_distance = volatility * self.stop_loss_atr_mult
            
            # Sanity check stop distance (min 0.2%, max 5%)
            if stop_distance < current_price * 0.002: stop_distance = current_price * 0.002
            if stop_distance > current_price * 0.05: stop_distance = current_price * 0.05
            
            sl_price = current_price - stop_distance
            risk_amt = current_price - sl_price
            
            # Take Profit is derived from Risk (R:R Ratio)
            tp_price = current_price + (risk_amt * self.reward_risk_ratio)
            
            # Execute Entry
            self.pos[sym] = {
                'entry_price': current_price,
                'stop_loss': sl_price,
                'take_profit': tp_price,
                'entry_tick': self.tick_count
            }
            
            return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['TREND_BRACKET']}
            
        return None