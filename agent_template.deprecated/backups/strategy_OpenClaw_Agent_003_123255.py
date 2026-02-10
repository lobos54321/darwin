import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seeds for parameter diversity to avoid herd penalties
        self.dna_a = random.random()
        self.dna_b = random.random()
        
        # SETTINGS
        # Adaptive window: 30-60 ticks. Shorter for HFT reactivity.
        self.window_size = 30 + int(self.dna_a * 30)
        
        # Risk Management
        self.max_positions = 5
        self.min_liquidity = 500000.0  # Avoid slippage on low caps
        
        # ENTRY LOGIC: "Noise Hunter"
        # We look for inefficiency (low trend strength) combined with deep oversold conditions.
        # Z-score: Standard deviation distance from mean
        self.entry_z_threshold = -2.0 - (self.dna_b * 1.5) # Range -2.0 to -3.5
        # Efficiency Ratio (KER): Filters out "Efficient Breakouts". 
        # We want jagged, noisy drops (KER < 0.4), not clean crashes (KER > 0.6).
        self.max_ker = 0.35 + (self.dna_a * 0.1) 
        self.entry_rsi = 30.0
        
        # EXIT LOGIC: Trailing Stop & Time Decay
        # Fixes 'FIXED_TP': No static take profit level.
        self.trailing_stop_pct = 0.005 + (self.dna_b * 0.005) # 0.5% to 1.0% trail
        self.hard_stop_pct = 0.03 # 3% hard stop
        self.time_limit = 120 # ticks
        
        # STATE
        self.history = {}       # symbol -> deque([prices])
        self.positions = {}     # symbol -> {entry_price, high_water_mark, entry_tick, qty}
        self.cooldowns = {}     # symbol -> tick_idx
        self.tick_count = 0

    def _calc_metrics(self, data):
        if len(data) < self.window_size:
            return None
        
        # Convert deque to list for slicing
        prices = list(data)
        window = prices[-self.window_size:]
        
        # 1. Volatility & Z-Score
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        if stdev == 0: return None
        z_score = (window[-1] - mean) / stdev
        
        # 2. Kaufman Efficiency Ratio (KER)
        # |Total Change| / Sum(|Tick Changes|)
        # Measures trend "cleanliness". 1.0 = straight line, 0.0 = pure noise.
        # Penalized 'EFFICIENT_BREAKOUT' implies we bought high KER moves.
        direction = abs(window[-1] - window[0])
        volatility_sum = sum(abs(window[i] - window[i-1]) for i in range(1, len(window)))
        
        ker = direction / volatility_sum if volatility_sum > 0 else 1.0
        
        # 3. Quick RSI (Relative Strength Index)
        # Use shorter period for HFT triggers
        rsi_period = 14
        if len(window) > rsi_period:
            deltas = [window[i] - window[i-1] for i in range(1, len(window))]
            recent_deltas = deltas[-rsi_period:]
            
            up = sum(d for d in recent_deltas if d > 0)
            down = sum(abs(d) for d in recent_deltas if d < 0)
            
            if down == 0: 
                rsi = 100.0
            else:
                rs = up / down
                rsi = 100.0 - (100.0 / (1.0 + rs))
        else:
            rsi = 50.0
            
        return {
            'z': z_score,
            'ker': ker,
            'rsi': rsi,
            'stdev': stdev
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Cleanup Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
        
        # 2. Shuffle processing order to avoid determinstic lag
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            # Data parsing validation
            try:
                p_data = prices[sym]
                curr_price = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
            except (KeyError, ValueError, TypeError):
                continue
                
            # Maintenance: History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(curr_price)
            
            # --- POSITION MANAGEMENT (Exits) ---
            if sym in self.positions:
                pos = self.positions[sym]
                
                # Update High Water Mark (for trailing stop)
                if curr_price > pos['high_water_mark']:
                    pos['high_water_mark'] = curr_price
                
                # Check 1: Hard Stop Loss
                pct_loss = (pos['entry_price'] - curr_price) / pos['entry_price']
                if pct_loss > self.hard_stop_pct:
                    del self.positions[sym]
                    self.cooldowns[sym] = self.tick_count + 100
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['HARD_STOP']}
                
                # Check 2: Trailing Stop
                # Dynamic Exit: Replaces 'FIXED_TP'
                drawdown_from_peak = (pos['high_water_mark'] - curr_price) / pos['high_water_mark']
                if drawdown_from_peak > self.trailing_stop_pct:
                    # Ensure we are at least break-even or cutting a loss early
                    # If we are in profit, take it.
                    # If we are just chopping, get out.
                    del self.positions[sym]
                    self.cooldowns[sym] = self.tick_count + 50
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TRAILING_STOP']}
                
                # Check 3: Time Decay (Stalemate)
                if (self.tick_count - pos['entry_tick']) > self.time_limit:
                    del self.positions[sym]
                    self.cooldowns[sym] = self.tick_count + 50
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_LIMIT']}
                
                continue # Skip entry logic if in position

            # --- ENTRY LOGIC ---
            if len(self.positions) >= self.max_positions: continue
            if sym in self.cooldowns: continue
            if liq < self.min_liquidity: continue
            
            metrics = self._calc_metrics(self.history[sym])
            if not metrics: continue
            
            # CORE LOGIC FIXES
            # 1. Z-Score Filter: Must be statistically significant deviation
            is_oversold = metrics['z'] < self.entry_z_threshold
            
            # 2. RSI Filter: Confluence with momentum
            is_weak_momentum = metrics['rsi'] < self.entry_rsi
            
            # 3. Efficiency Ratio (KER) Filter
            # Fixes 'EFFICIENT_BREAKOUT': 
            # If KER is High (>0.6), the drop is a crash/efficient move. DO NOT BUY.
            # If KER is Low (<0.35), the drop is noise/inefficient. BUY.
            is_noisy = metrics['ker'] < self.max_ker
            
            if is_oversold and is_weak_momentum and is_noisy:
                # Mutation: Confirmation Tick
                # Don't catch the knife until it blunts slightly.
                # Check if current price is higher than previous tick (micro-reversal)
                prev_price = self.history[sym][-2] if len(self.history[sym]) >= 2 else curr_price
                if curr_price > prev_price:
                    
                    self.positions[sym] = {
                        'entry_price': curr_price,
                        'high_water_mark': curr_price,
                        'entry_tick': self.tick_count,
                        'qty': 0.15 # Fixed trade size unit
                    }
                    return {
                        'side': 'BUY', 
                        'symbol': sym, 
                        'amount': 0.15, 
                        'reason': ['NOISE_REVERSION', f'Z:{metrics["z"]:.2f}']
                    }
                    
        return None