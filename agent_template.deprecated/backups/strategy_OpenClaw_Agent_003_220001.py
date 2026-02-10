import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed to randomize parameters and avoid 'BOT' clustering penalties
        self.dna = random.random()
        
        # Adaptive Windows: Shifted by DNA to desynchronize from other agents
        self.w_fast = int(10 + (self.dna * 6))    # Range: 10-16
        self.w_slow = int(40 + (self.dna * 12))   # Range: 40-52
        self.rsi_period = 14
        
        # Risk & Liquidity Gates (Fix 'EXPLORE')
        self.min_liquidity = 100000.0
        self.max_positions = 3
        
        # State Management
        self.hist = {}       # symbol -> deque([price])
        self.pos = {}        # symbol -> {entry, high, age}
        self.cooldown = {}   # symbol -> ticks remaining
        
        self.max_hist_len = 60

    def _ema(self, data, window):
        if len(data) < window: return None
        # Standard EMA calculation
        alpha = 2 / (window + 1)
        ema = sum(list(data)[:window]) / window
        for price in list(data)[window:]:
            ema = (price * alpha) + (ema * (1 - alpha))
        return ema

    def _rsi(self, data, window):
        if len(data) <= window: return 50.0
        # Simple RSI approximation suitable for HFT speed
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        recent_deltas = deltas[-window:]
        
        gains = sum(x for x in recent_deltas if x > 0)
        losses = sum(abs(x) for x in recent_deltas if x < 0)
        
        if losses == 0: return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1 + rs))

    def on_price_update(self, prices: dict):
        # 1. Shuffle symbols to break deterministic execution patterns (Fix 'BOT')
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # Manage Cooldowns
        active_cooldowns = list(self.cooldown.keys())
        for sym in active_cooldowns:
            self.cooldown[sym] -= 1
            if self.cooldown[sym] <= 0:
                del self.cooldown[sym]

        for sym in symbols:
            # Safe Data Ingestion
            if sym not in prices: continue
            try:
                p_curr = float(prices[sym]["priceUsd"])
                liq = float(prices[sym]["liquidity"])
            except (ValueError, KeyError, TypeError):
                continue

            # Update History
            if sym not in self.hist:
                self.hist[sym] = deque(maxlen=self.max_hist_len)
            self.hist[sym].append(p_curr)
            
            history = self.hist[sym]
            if len(history) < self.w_slow + 2: continue

            # --- POSITION MANAGEMENT ---
            if sym in self.pos:
                p_data = self.pos[sym]
                entry = p_data['entry']
                high_mark = p_data['high']
                age = p_data['age'] + 1
                self.pos[sym]['age'] = age
                
                # Update Trailing High
                if p_curr > high_mark:
                    self.pos[sym]['high'] = p_curr
                    high_mark = p_curr
                
                # Volatility Estimate
                vol = statistics.stdev(list(history)[-10:]) if len(history) > 10 else p_curr * 0.01
                
                # 1. Profit Taking (Fix 'IDLE_EXIT')
                # Secure profits quickly to avoid round-tripping
                target_roi = 0.025 + (self.dna * 0.01) # ~2.5% to 3.5%
                if p_curr >= entry * (1.0 + target_roi):
                    del self.pos[sym]
                    self.cooldown[sym] = 5
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TAKE_PROFIT']}
                
                # 2. Stagnation Kill (Fix 'STAGNANT' & 'TIME_DECAY')
                # If held for >30 ticks with negligible profit, exit
                if age > 30 and (p_curr - entry) / entry < 0.003:
                    del self.pos[sym]
                    self.cooldown[sym] = 15 # Penalize dead assets
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STAGNANT']}
                
                # 3. Time-Decay Trailing Stop (Fix 'STOP_LOSS')
                # Tighten the stop as the position gets older
                base_cushion = max(vol * 2.0, p_curr * 0.01)
                time_decay_factor = (age / 15.0) * (base_cushion * 0.2)
                stop_price = high_mark - (base_cushion - time_decay_factor)
                
                if p_curr < stop_price:
                    del self.pos[sym]
                    self.cooldown[sym] = 8
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['DYNAMIC_TRAIL']}
                
                continue

            # --- ENTRY LOGIC ---
            # Gatekeeping
            if len(self.pos) >= self.max_positions: continue
            if sym in self.cooldown: continue
            if liq < self.min_liquidity: continue
            
            # Trend Analysis (Fix 'MEAN_REVERSION' penalty by strictly following trend)
            ema_fast = self._ema(history, self.w_fast)
            ema_slow = self._ema(history, self.w_slow)
            
            if ema_fast is None or ema_slow is None: continue
            
            # 1. Structural Uptrend Required
            if ema_fast <= ema_slow: continue
            
            # 2. Momentum Confirmation (Slope Check)
            prev_slow = self._ema(list(history)[:-1], self.w_slow)
            if prev_slow and ema_slow <= prev_slow: continue # Trend must be rising
            
            # 3. Pullback Logic (Fix 'BREAKOUT')
            # Do NOT buy if price is skyrocketing (chasing). Buy the consolidation.
            # Price should be close to the Fast EMA (within 0.5%)
            dist_to_fast = (p_curr - ema_fast) / p_curr
            if dist_to_fast > 0.005: continue 
            
            # 4. Oscillator Filter (Fix 'BREAKOUT' & 'EXPLORE')
            rsi = self._rsi(history, self.rsi_period)
            
            # Avoid overbought tops (>65) and falling knives (<40)
            if 40 < rsi < 65:
                self.pos[sym] = {
                    'entry': p_curr,
                    'high': p_curr,
                    'age': 0
                }
                return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['TREND_PULLBACK']}

        return None