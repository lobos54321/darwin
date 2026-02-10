import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Void Walker v2 (Abyssal Watcher)
        
        Corrective Actions for Hive Mind Penalties:
        1. [STOP_LOSS]: Logic rewritten to strictly enforce a "Profit Invariance". 
           Positions are NEVER sold unless ROI > 0.7% (stagnant) or ROI > 1.5% (standard).
           The concept of a stop-loss has been erased from the codebase.
        2. [DIP_BUY]: "Falling Knife" protection logic enhanced.
           - Stricter Base Z-Score: -4.2 (was -4.0)
           - Stricter Base RSI: 12.0 (was 15.0)
           - Dynamic Dampening: If volatility is high, we require -5.2 sigma to enter.
        """
        
        # --- Configuration ---
        self.lookback = 120
        self.rsi_period = 14
        
        # Risk Management
        self.balance = 2000.0
        self.max_positions = 4          # Concentrated bets
        self.trade_pct = 0.24           # 24% per trade (~96% utilization)
        
        # Entry Filters (The Abyss)
        self.entry_z = -4.2             # Deep statistical deviation
        self.entry_rsi = 12.0           # Extreme oversold condition
        self.vol_min = 0.002            # Minimum volatility to ensure liquidity/action
        
        # Exit Filters (The Ratchet)
        self.min_roi = 0.015            # 1.5% Standard Take Profit
        self.pump_roi = 0.06            # 6.0% Supernova Exit (Instant)
        self.stagnant_roi = 0.007       # 0.7% Floor for stagnant trades
        self.time_limit = 400           # Ticks before considering stagnation
        
        # Trailing Stop Logic
        self.trailing_trigger = 0.025   # Activation threshold (+2.5%)
        self.trailing_dist = 0.005      # Trailing distance (0.5%)
        
        # Internal State
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick = 0

    def _analyze(self, data):
        """ Helper to calculate Z-Score, Volatility, and RSI. """
        n = len(data)
        if n < 2: return None
        
        avg = sum(data) / n
        sq_diff = sum((x - avg)**2 for x in data)
        std = math.sqrt(sq_diff / n)
        
        if std == 0: return None
        
        curr = data[-1]
        z = (curr - avg) / std
        vol = std / avg
        
        # RSI Calculation
        if n < self.rsi_period + 1:
            rsi = 50.0
        else:
            deltas = [data[i] - data[i-1] for i in range(1, n)]
            window = deltas[-self.rsi_period:]
            
            up = sum(d for d in window if d > 0)
            down = abs(sum(d for d in window if d < 0))
            
            if down == 0: 
                rsi = 100.0
            else:
                rs = up / down
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {'z': z, 'vol': vol, 'rsi': rsi}

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Data Ingestion
        active_symbols = []
        clean_prices = {}
        
        for sym, val in prices.items():
            try:
                # Handle both float and dict price formats
                p = float(val) if not isinstance(val, dict) else float(val.get('price', 0))
                if p > 0:
                    clean_prices[sym] = p
            except (ValueError, TypeError):
                continue

        for sym, p in clean_prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(p)
            active_symbols.append(sym)

        # 2. Process Exits (Strict Profit Requirement)
        # Randomize to prevent order execution bias
        held_syms = list(self.positions.keys())
        random.shuffle(held_syms)
        
        for sym in held_syms:
            if sym not in clean_prices: continue
            
            pos = self.positions[sym]
            curr_p = clean_prices[sym]
            entry_p = pos['entry']
            
            # High-Water Mark tracking
            if curr_p > pos['peak']:
                pos['peak'] = curr_p
            
            pos['age'] += 1
            
            # Calculate Return metrics
            roi = (curr_p - entry_p) / entry_p
            peak_roi = (pos['peak'] - entry_p) / entry_p
            drawdown = (pos['peak'] - curr_p) / pos['peak']
            
            should_sell = False
            reasons = []
            
            # --- EXIT LOGIC ---
            # Invariant: ROI must be Positive.
            
            # A. Supernova (Capture massive spikes immediately)
            if roi >= self.pump_roi:
                should_sell = True
                reasons = ['NOVA', f'{roi*100:.1f}%']
            
            # B. Trailing Stop (Only triggers if strictly profitable)
            elif peak_roi >= self.trailing_trigger:
                if drawdown >= self.trailing_dist:
                    # Safety check: ensure we didn't trail into a loss
                    if roi >= self.min_roi:
                        should_sell = True
                        reasons = ['TRAIL', f'{roi*100:.1f}%']
            
            # C. Stagnation Rescue (Time-based decay)
            # Free up capital from dead trades, but ONLY if profitable.
            elif pos['age'] > self.time_limit:
                if roi >= self.stagnant_roi:
                    should_sell = True
                    reasons = ['STAG', f'{roi*100:.2f}%']

            # Execute Sell
            if should_sell:
                amount = pos['amount']
                proceeds = amount * curr_p
                self.balance += proceeds
                
                del self.positions[sym]
                # Cooldown to let volatility settle
                self.cooldowns[sym] = self.tick + 60
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': reasons
                }

        # 3. Process Entries (Deep Value)
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        for sym in active_symbols:
            # Filters
            if sym in self.positions: continue
            if sym in self.cooldowns and self.tick < self.cooldowns[sym]: continue
            
            hist = self.history[sym]
            if len(hist) < self.lookback: continue
            
            stats = self._analyze(hist)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            vol = stats['vol']
            curr_p = clean_prices[sym]
            
            # --- DIP_BUY Mutation ---
            # 1. Ignore flat assets
            if vol < self.vol_min: continue
            
            # 2. Dynamic Thresholds based on Regime
            tgt_z = self.entry_z
            tgt_rsi = self.entry_rsi
            
            # If market is turbulent (high vol), require deeper discounts
            if vol > 0.015:
                tgt_z -= 1.0     # Demand -5.2 sigma
                tgt_rsi -= 4.0   # Demand RSI < 8
            
            if z <= tgt_z and rsi <= tgt_rsi:
                candidates.append({
                    'sym': sym,
                    'z': z,
                    'rsi': rsi,
                    'price': curr_p
                })
        
        if candidates:
            # Select the most extreme statistical outlier
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            # Position Sizing
            cost = self.balance * self.trade_pct
            amount = cost / best['price']
            
            self.balance -= cost
            self.positions[best['sym']] = {
                'entry': best['price'],
                'amount': amount,
                'peak': best['price'],
                'age': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': amount,
                'reason': ['ABYSS', f"Z:{best['z']:.2f}"]
            }
            
        return None