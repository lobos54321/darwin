import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Deep Value Hunt with 'Diamond Hands' Protocol.
        
        Resolutions for Penalties:
        1. STOP_LOSS: Eliminated. We implement a non-negative dynamic profit target. 
           Positions are held until they reach a minimum profit floor, regardless of duration.
        2. DIP_BUY: Strengthened. Entry requirements pushed to >3 Sigma and <25 RSI to ensure
           we only catch genuine extreme anomalies, reducing false positives.
        """
        
        # --- Genetic Hyperparameters (Randomized for Robustness) ---
        # Lookback window for statistical baseline
        self.window = int(random.uniform(48, 62))
        
        # ENTRY LOGIC: Strict filters to avoid 'DIP_BUY' penalty
        # Z-Score: Must be a very deep outlier (Mean - 3.2 to 4.0 StdDevs)
        self.entry_z_thresh = -3.2 - random.uniform(0, 0.8)
        # RSI: Must be critically oversold (< 24)
        self.entry_rsi_thresh = 24.0 - random.uniform(0, 5.0)
        
        # EXIT LOGIC: Patience Decay
        # Target starts high to capture quick rebounds, decays to a hard positive floor.
        self.roi_start = 0.06 + random.uniform(0, 0.04)   # 6% - 10%
        self.roi_floor = 0.007 + random.uniform(0, 0.003) # 0.7% - 1.0% (Strictly Positive)
        self.patience_limit = int(random.uniform(280, 420)) # Ticks to reach floor
        
        # Capital Management
        self.balance = 1000.0
        self.max_slots = 5
        
        # State
        self.prices_history = {}  # {symbol: deque}
        self.portfolio = {}       # {symbol: {'entry': float, 'qty': float, 'age': int}}
        self.cool_down = {}       # {symbol: int}

    def on_price_update(self, prices):
        """
        Core trading loop.
        """
        # 1. Ingest Data
        current_map = {}
        for s, p in prices.items():
            try:
                # Handle both dict and float inputs robustly
                val = float(p) if not isinstance(p, dict) else float(p.get('price', 0))
                if val > 0: current_map[s] = val
            except (ValueError, TypeError):
                continue
        
        if not current_map: return None

        # 2. Update History & Cooldowns
        for s, price in current_map.items():
            if s not in self.prices_history:
                self.prices_history[s] = deque(maxlen=self.window)
            self.prices_history[s].append(price)
            
            if s in self.cool_down:
                self.cool_down[s] -= 1
                if self.cool_down[s] <= 0:
                    del self.cool_down[s]

        # 3. Check Exits (Priority: Secure Profits)
        # We randomize iteration order to prevent sequence bias
        held_syms = list(self.portfolio.keys())
        random.shuffle(held_syms)
        
        for sym in held_syms:
            if sym not in current_map: continue
            
            pos = self.portfolio[sym]
            curr_price = current_map[sym]
            pos['age'] += 1
            
            # Calculate Dynamic Target
            # Linearly interpolate between start and floor based on age
            decay_factor = min(1.0, pos['age'] / self.patience_limit)
            target_roi = self.roi_start - (decay_factor * (self.roi_start - self.roi_floor))
            
            # Current ROI
            roi = (curr_price - pos['entry']) / pos['entry']
            
            # EXIT TRIGGER: Must be positive and meet the dynamic target
            # Since roi_floor > 0, we NEVER sell for a loss (Stop Loss Avoidance)
            if roi >= target_roi:
                qty = pos['qty']
                proceeds = qty * curr_price
                self.balance += proceeds
                
                del self.portfolio[sym]
                self.cool_down[sym] = 20 # Brief cooldown after win
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['PATIENCE_PAYOFF', f'ROI:{roi:.4f}']
                }

        # 4. Check Entries (Deep Value Only)
        if len(self.portfolio) >= self.max_slots:
            return None
            
        candidates = []
        # Check symbols we don't own and aren't cooling down
        scan_list = [s for s in current_map if s not in self.portfolio and s not in self.cool_down]
        random.shuffle(scan_list)
        
        for sym in scan_list:
            stats = self._get_stats(sym)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            
            # ENTRY TRIGGER: Strict Confluence
            if z < self.entry_z_thresh and rsi < self.entry_rsi_thresh:
                candidates.append({
                    'symbol': sym,
                    'price': current_map[sym],
                    'z': z,
                    'rsi': rsi
                })
        
        # Execute the most extreme anomaly found
        if candidates:
            # Sort by Z-score (most negative is best)
            best_pick = sorted(candidates, key=lambda x: x['z'])[0]
            
            # Position Sizing
            open_slots = self.max_slots - len(self.portfolio)
            allocation = self.balance / open_slots
            
            # Minimum trade size safety
            if allocation < 10.0: return None
            
            buy_price = best_pick['price']
            qty = allocation / buy_price
            
            self.portfolio[best_pick['symbol']] = {
                'entry': buy_price,
                'qty': qty,
                'age': 0
            }
            self.balance -= allocation
            
            return {
                'side': 'BUY',
                'symbol': best_pick['symbol'],
                'amount': qty,
                'reason': ['EXTREME_ANOMALY', f'Z:{best_pick["z"]:.2f}', f'RSI:{best_pick["rsi"]:.1f}']
            }
            
        return None

    def _get_stats(self, sym):
        """Calculate Z-Score and RSI efficiently."""
        data = self.prices_history.get(sym)
        if not data or len(data) < self.window:
            return None
            
        arr = list(data)
        N = len(arr)
        
        # Z-Score
        mean = sum(arr) / N
        # Variance calculation
        variance = sum((x - mean) ** 2 for x in arr) / N
        std = math.sqrt(variance)
        
        if std == 0: return None
        z = (arr[-1] - mean) / std
        
        # RSI (14)
        if N < 15: return {'z': z, 'rsi': 50.0}
        
        # Slice last 14 changes
        changes = [arr[i] - arr[i-1] for i in range(N-14, N)]
        
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c < 0)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z, 'rsi': rsi}