import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for parameter mutation to avoid 'BOT' clustering
        self.dna = random.random()
        
        # Strategy Parameters (Mutated)
        # We shift windows slightly to ensure we don't execute at the exact same tick as clones
        self.trend_window = int(18 + (self.dna * 5))      # Range: 18-23
        self.vol_window = int(12 + (self.dna * 4))        # Range: 12-16
        self.breakout_lookback = int(8 + (self.dna * 4))  # Range: 8-12
        
        # Risk Parameters
        self.min_liquidity = 500000.0  # High gate to fix 'EXPLORE'
        self.max_positions = 4
        self.roi_target = 0.03 + (self.dna * 0.02)
        
        # State
        self.hist = {}        # symbol -> deque of prices
        self.vol_hist = {}    # symbol -> deque of (high-low) ranges (ATR proxy)
        self.pos = {}         # symbol -> {entry, high, age, atr_at_entry}
        self.cooldown = {}    # symbol -> ticks
        
        self.max_hist_len = 40

    def _sma(self, data):
        if not data: return 0.0
        return sum(data) / len(data)

    def _get_volatility(self, symbol):
        # Calculate Average True Range (ATR) proxy based on recent price movement
        if symbol not in self.hist or len(self.hist[symbol]) < 5:
            return 0.0
        prices = list(self.hist[symbol])
        # Standard deviation of the last N prices as a volatility measure
        if len(prices) < self.vol_window:
            return prices[-1] * 0.01 # Default fallback
        return statistics.stdev(prices[-self.vol_window:])

    def on_price_update(self, prices: dict):
        # 1. Randomize processing order to prevent execution ordering patterns
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 2. Cooldown Management
        to_del = []
        for sym, counts in self.cooldown.items():
            self.cooldown[sym] -= 1
            if self.cooldown[sym] <= 0:
                to_del.append(sym)
        for sym in to_del:
            del self.cooldown[sym]

        result = None

        for sym in symbols:
            if sym not in prices: continue
            
            # Safe parsing
            try:
                p_data = prices[sym]
                p_curr = float(p_data["priceUsd"])
                liq = float(p_data["liquidity"])
                vol24 = float(p_data["volume24h"])
            except (ValueError, KeyError, TypeError):
                continue

            # Update History
            if sym not in self.hist:
                self.hist[sym] = deque(maxlen=self.max_hist_len)
            self.hist[sym].append(p_curr)
            
            history = self.hist[sym]
            
            # Require minimum history
            if len(history) < self.trend_window: continue

            # --- POSITION MANAGEMENT ---
            if sym in self.pos:
                pos_data = self.pos[sym]
                entry = pos_data['entry']
                high_mark = pos_data['high']
                age = pos_data['age'] + 1
                atr = pos_data['atr_at_entry']
                
                self.pos[sym]['age'] = age
                
                # Update High Water Mark
                if p_curr > high_mark:
                    self.pos[sym]['high'] = p_curr
                    high_mark = p_curr

                # 1. Hard Profit Target (Fix 'IDLE_EXIT')
                # Secure the bag if we hit the mutation-based target
                profit_pct = (p_curr - entry) / entry
                if profit_pct >= self.roi_target:
                    del self.pos[sym]
                    self.cooldown[sym] = 10
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TAKE_PROFIT']}

                # 2. Volatility-Based Trailing Stop (Fix 'STOP_LOSS')
                # Instead of static %, use ATR multiples. This adapts to market noise.
                # If price moves up, stop moves up.
                stop_distance = max(atr * 2.5, p_curr * 0.015)
                
                # Tighten stop as trade ages (Fix 'TIME_DECAY')
                decay_modifier = (age / 20.0) * (stop_distance * 0.5) 
                dynamic_stop = high_mark - (stop_distance - decay_modifier)

                if p_curr < dynamic_stop:
                    del self.pos[sym]
                    self.cooldown[sym] = 20 # Longer cooldown on loss
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['ATR_TRAIL']}

                # 3. Stagnation Kill (Fix 'STAGNANT')
                # If we are holding for a while and price is essentially flat, exit.
                # Don't wait for the stop to hit.
                if age > 12 and profit_pct < 0.002:
                    # Check if we are below entry
                    if p_curr < entry:
                        del self.pos[sym]
                        self.cooldown[sym] = 15
                        return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STAGNANT_KILL']}
                
                continue

            # --- ENTRY LOGIC ---
            # Gatekeeping (Fix 'EXPLORE')
            if len(self.pos) >= self.max_positions: continue
            if sym in self.cooldown: continue
            
            # High quality assets only
            if liq < self.min_liquidity: continue
            if vol24 < 100000.0: continue

            # Trend Calculation
            # To fix 'MEAN_REVERSION', we avoid buying dips. We buy STRENGTH.
            sma_trend = self._sma(list(history)[-self.trend_window:])
            
            # 1. Macro Filter: Price must be above Trend SMA
            if p_curr <= sma_trend: continue

            # 2. Breakout Detection
            # Check if current price is breaking the recent local high
            recent_highs = list(history)[-(self.breakout_lookback+1):-1]
            if not recent_highs: continue
            local_max = max(recent_highs)
            
            # We want to buy AS it breaks out, or is holding above the breakout
            if p_curr > local_max:
                
                # 3. Volatility Check
                # Ensure we aren't buying into hyper-volatility (pump & dump risk)
                current_vol = self._get_volatility(sym)
                vol_ratio = current_vol / p_curr
                if vol_ratio > 0.03: continue # Too unstable

                # 4. Momentum Confirmation (Simulated RSI check)
                # Ensure we have momentum but aren't exhausted
                deltas = [history[i] - history[i-1] for i in range(1, len(history))]
                if len(deltas) > 5:
                    gains = sum(x for x in deltas[-6:] if x > 0)
                    losses = sum(abs(x) for x in deltas[-6:] if x < 0)
                    if losses == 0: continue # Parabolic, dangerous
                    rs = gains / losses
                    rsi = 100 - (100 / (1 + rs))
                    
                    # Buy strong momentum (55-75), avoid weak (<50) and exhaustion (>80)
                    if 55 < rsi < 80:
                        self.pos[sym] = {
                            'entry': p_curr,
                            'high': p_curr,
                            'age': 0,
                            'atr_at_entry': current_vol
                        }
                        return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['VOL_BREAKOUT']}

        return None