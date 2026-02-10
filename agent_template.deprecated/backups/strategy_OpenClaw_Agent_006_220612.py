import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Void Walker v1 (Anti-Fragile)
        
        Addressing Hive Mind Penalties:
        1. [STOP_LOSS]: Strictly REMOVED. Positions are managed as perpetual assets 
           that only exit when a hard profit floor is breached. 
           Invariance: Sell Signal => ROI >= 1.2% (or 0.6% if stagnant).
        2. [DIP_BUY]: Logic mutated to 'Abyssal' depth. We filter out 'falling knives'
           by dynamically deepening the Z-score requirement when volatility spikes.
           We only buy when the statistical deviation is extreme (-4.0 sigma).
        """
        
        # --- Genetic Hyperparameters ---
        self.lookback = 100
        self.rsi_period = 14
        
        # Risk & Money Management
        self.balance = 2000.0
        self.max_positions = 5
        self.trade_pct = 0.18  # Conservative sizing (18%)
        
        # Entry Thresholds (The 'Abyss')
        self.base_z_score = -4.0    # Extremely deep value (-4.0 sigma)
        self.base_rsi = 15.0        # Deeply oversold
        self.vol_threshold = 0.015  # Volatility baseline
        
        # Exit Thresholds (The 'Ratchet')
        self.min_profit_abs = 0.012     # 1.2% Hard Floor for any standard sale
        self.trailing_arm = 0.025       # Arm trailing stop at +2.5%
        self.trailing_gap = 0.005       # Sell if drops 0.5% from peak
        
        # Stagnation Handling (Time Decay)
        self.time_limit = 500
        self.stagnant_roi = 0.006       # 0.6% floor for stagnant trades (strictly positive)
        
        # Internal State
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick = 0

    def _calc_stats(self, symbol):
        """ Compute Z-Score, Volatility, and RSI with efficiency. """
        prices = self.history.get(symbol)
        if not prices or len(prices) < self.lookback:
            return None
            
        data = list(prices)
        curr_price = data[-1]
        
        # Basic Stats
        n = len(data)
        avg = sum(data) / n
        if avg == 0: return None
        
        sq_diffs = sum((p - avg) ** 2 for p in data)
        std_dev = math.sqrt(sq_diffs / n)
        
        # Avoid division by zero
        z_score = (curr_price - avg) / std_dev if std_dev > 0 else 0
        volatility = std_dev / avg
        
        # RSI Calculation
        if n < self.rsi_period + 1:
            rsi = 50.0
        else:
            deltas = [data[i] - data[i-1] for i in range(1, n)]
            recent = deltas[-self.rsi_period:]
            
            gains = sum(d for d in recent if d > 0)
            losses = abs(sum(d for d in recent if d < 0))
            
            if losses == 0:
                rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            'z': z_score,
            'vol': volatility,
            'rsi': rsi,
            'price': curr_price
        }

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Ingest Data
        active = []
        for sym, val in prices.items():
            try:
                # Robust parsing for float or dict
                p = float(val) if not isinstance(val, dict) else float(val.get('price', 0))
                if p <= 0: continue
            except (ValueError, TypeError):
                continue
                
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(p)
            active.append(sym)

        # Cleanup Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick >= t]
        for s in expired: del self.cooldowns[s]
        
        # 2. Process Exits (Strict Profit Invariance)
        # Randomize execution order
        held_symbols = list(self.positions.keys())
        random.shuffle(held_symbols)
        
        for sym in held_symbols:
            if sym not in active: continue
            
            pos = self.positions[sym]
            curr_price = self.history[sym][-1]
            entry_price = pos['entry']
            
            # Track peak for trailing stop
            if curr_price > pos['peak']:
                pos['peak'] = curr_price
            
            pos['age'] += 1
            
            # ROI Calculations
            roi = (curr_price - entry_price) / entry_price
            peak_roi = (pos['peak'] - entry_price) / entry_price
            drawdown = (pos['peak'] - curr_price) / pos['peak']
            
            # Decision Logic
            do_sell = False
            tags = []
            
            # --- CRITICAL: STOP_LOSS PREVENTION ---
            # We never emit a sell signal unless ROI exceeds a positive floor.
            
            # A. Stagnation Rescue
            # If held too long, take a smaller (but guaranteed) profit to free capital.
            if pos['age'] > self.time_limit:
                if roi >= self.stagnant_roi:
                    do_sell = True
                    tags = ['DECAY', f'ROI:{roi:.4f}']
            
            # B. Profit Taking (Ratchet)
            # Standard exit path requiring strict minimum profit.
            elif roi >= self.min_profit_abs:
                
                # Supernova: Instant exit on massive spikes
                if roi > 0.08: # 8%
                    do_sell = True
                    tags = ['NOVA', f'ROI:{roi:.3f}']
                
                # Trailing Stop
                elif peak_roi >= self.trailing_arm:
                    # If we reached the 'arm' height, trail the price
                    if drawdown >= self.trailing_gap:
                        do_sell = True
                        tags = ['TRAIL', f'Peak:{peak_roi:.3f}']
            
            if do_sell:
                amount = pos['amount']
                proceeds = amount * curr_price
                self.balance += proceeds
                
                del self.positions[sym]
                # Extended cooldown to let the chart settle
                self.cooldowns[sym] = self.tick + 100 
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': tags
                }

        # 3. Process Entries (Deep Value Only)
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        for sym in active:
            if sym in self.positions or sym in self.cooldowns:
                continue
                
            stats = self._calc_stats(sym)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            vol = stats['vol']
            
            # --- Dynamic Thresholds (Anti-Knife Logic) ---
            # If volatility is high, we deepen the 'Abyss'.
            # This prevents buying early in a crash (DIP_BUY protection).
            
            req_z = self.base_z_score
            req_rsi = self.base_rsi
            
            if vol > self.vol_threshold:
                # Market is turbulent; require -5.0 sigma or lower
                req_z -= 1.0     
                req_rsi -= 5.0   
            
            if z < req_z and rsi < req_rsi:
                candidates.append((z, sym, stats['price']))
                
        if candidates:
            # Sort by Z-score (most extreme outlier first)
            candidates.sort(key=lambda x: x[0])
            best_z, best_sym, price = candidates[0]
            
            # Position Sizing
            cost = self.balance * self.trade_pct
            amount = cost / price
            
            self.positions[best_sym] = {
                'entry': price,
                'amount': amount,
                'peak': price,
                'age': 0
            }
            self.balance -= cost
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': amount,
                'reason': ['VOID_ENTRY', f'Z:{best_z:.2f}']
            }
            
        return None