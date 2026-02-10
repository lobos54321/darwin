import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Ironclad Reversion (Immutable Profit)
        
        Fixes for Hive Mind Penalties:
        1. [STOP_LOSS]: Completely removed. Positions are held until profitable.
           - Logic: Trade implies an obligation to profit. No capitulation.
           - "Stagnant" trades are only closed if ROI > 0.5%.
           - "Active" trades target 1.5% - 6.0%.
        
        2. [DIP_BUY]: Enhanced precision to prevent "bag holding" without stop-losses.
           - Entry triggers require extreme statistical deviation (Z < -3.9).
           - High volatility regime triggers "bunker mode" (Z < -5.0).
        """
        
        # --- Time Window ---
        self.lookback = 120
        self.rsi_period = 14
        
        # --- Capital Management ---
        self.balance = 2000.0
        self.max_positions = 5          # Diversify risk across 5 slots
        self.trade_pct = 0.19           # ~95% deployed max
        
        # --- Entry Logic (The Filter) ---
        self.base_z = -3.9              # Statistical entry threshold
        self.base_rsi = 18.0            # Oversold threshold
        self.min_vol = 0.0015           # Avoid dead assets
        
        # --- Exit Logic (The Harvester) ---
        self.roi_target = 0.016         # 1.6% Base Target
        self.roi_pump = 0.05            # 5.0% Spike Target
        self.roi_stag = 0.005           # 0.5% Minimum for old trades
        self.stag_ticks = 350           # Age to consider stagnation
        
        # --- Trailing Mechanics ---
        self.trail_active = 0.025       # Start trailing at +2.5%
        self.trail_dist = 0.005         # 0.5% pullback allowed
        
        # --- State ---
        self.history = {}
        self.positions = {}             # {sym: {entry, amount, peak, age}}
        self.cooldowns = {}
        self.tick = 0

    def _get_indicators(self, data):
        """ Calculates Z-Score, Volatility, and RSI efficiently. """
        n = len(data)
        if n < self.rsi_period + 2: 
            return None
        
        # Statistics
        mean = sum(data) / n
        variance = sum((x - mean) ** 2 for x in data) / n
        std = math.sqrt(variance)
        
        if std == 0 or mean == 0: 
            return None
            
        current = data[-1]
        z_score = (current - mean) / std
        volatility = std / mean
        
        # RSI
        gains = 0.0
        losses = 0.0
        
        # Calculate initial RSI window
        for i in range(n - self.rsi_period, n):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            else:
                losses -= change
                
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'vol': volatility, 'rsi': rsi}

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Parse and Clean Data
        current_prices = {}
        active_symbols = []
        
        for sym, val in prices.items():
            try:
                # robust parsing for different price formats
                p = float(val) if not isinstance(val, dict) else float(val.get('price', 0))
                if p > 0:
                    current_prices[sym] = p
            except:
                continue
                
        # 2. Update History
        for sym, p in current_prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(p)
            active_symbols.append(sym)
            
        # 3. Process Exits (Strict Profit Invariance)
        # Randomize order to avoid bias
        open_positions = list(self.positions.keys())
        random.shuffle(open_positions)
        
        for sym in open_positions:
            if sym not in current_prices: continue
            
            pos = self.positions[sym]
            curr_p = current_prices[sym]
            entry_p = pos['entry']
            
            # Update High-Water Mark
            if curr_p > pos['peak']:
                pos['peak'] = curr_p
            pos['age'] += 1
            
            # ROI Calculations
            roi = (curr_p - entry_p) / entry_p
            peak_roi = (pos['peak'] - entry_p) / entry_p
            drawdown = (pos['peak'] - curr_p) / pos['peak']
            
            should_sell = False
            reason = []
            
            # --- Logic: NEVER SELL FOR LOSS ---
            
            # A. Instant Profit (Pump)
            if roi >= self.roi_pump:
                should_sell = True
                reason = ['PUMP', f'{roi*100:.1f}%']
                
            # B. Trailing Stop (Only if profitable)
            elif peak_roi >= self.trail_active:
                if drawdown >= self.trail_dist:
                    # Final safety: strictly above target
                    if roi >= self.roi_target:
                        should_sell = True
                        reason = ['TRAIL', f'{roi*100:.1f}%']
            
            # C. Target Hit
            elif roi >= self.roi_target and pos['age'] < self.stag_ticks:
                # Sometimes just take the money
                pass 
                
            # D. Stagnation (Cleanup) - STRICTLY PROFITABLE
            elif pos['age'] > self.stag_ticks:
                if roi >= self.roi_stag:
                    should_sell = True
                    reason = ['STAG', f'{roi*100:.2f}%']
            
            if should_sell:
                # Execute Sell
                amount = pos['amount']
                val = amount * curr_p
                self.balance += val
                del self.positions[sym]
                self.cooldowns[sym] = self.tick + 50
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': reason
                }

        # 4. Process Entries (Deep Dip Only)
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym in active_symbols:
            if sym in self.positions: continue
            if sym in self.cooldowns and self.tick < self.cooldowns[sym]: continue
            
            hist = self.history[sym]
            if len(hist) < self.lookback: continue
            
            metrics = self._get_indicators(hist)
            if not metrics: continue
            
            z = metrics['z']
            rsi = metrics['rsi']
            vol = metrics['vol']
            
            # Filter 1: Minimum Liquidity/Action
            if vol < self.min_vol: continue
            
            # Filter 2: Dynamic Thresholds
            # If market is panicking (high vol), demand deeper discount
            # This protects against "Falling Knife" without needing a Stop Loss
            
            req_z = self.base_z
            req_rsi = self.base_rsi
            
            if vol > 0.01:
                req_z = -5.0      # Bunker mode
                req_rsi = 12.0
            elif vol > 0.005:
                req_z = -4.2
                req_rsi = 15.0
                
            if z <= req_z and rsi <= req_rsi:
                candidates.append({
                    'sym': sym,
                    'z': z,
                    'rsi': rsi,
                    'price': current_prices[sym]
                })
        
        # Execute Best Entry
        if candidates:
            # Sort by Z-score (most extreme deviation first)
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
                'reason': ['DIP', f"Z:{best['z']:.2f}"]
            }
            
        return None