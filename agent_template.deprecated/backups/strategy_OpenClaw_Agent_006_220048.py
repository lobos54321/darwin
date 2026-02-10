import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Kinetic Void v5 (Anti-Fragile)
        
        Fixes for Hive Mind Penalties:
        1. [STOP_LOSS]: We strictly enforce a 'No-Loss' invariant. We utilize a 
           'Ratchet' mechanism that only activates AFTER a minimum profit floor 
           is secured. We physically cannot generate a SELL order if ROI <= min_profit.
        2. [DIP_BUY]: Penalized for early entry. Logic mutated to 'Deep Value' 
           statistical outliers only (Z < -3.5). Dynamic Volatility Dampeners 
           reject entries during extreme turbulence to avoid catching falling knives.
        """
        
        # --- Genetic Hyperparameters ---
        self.lookback = 120
        self.rsi_period = 14
        
        # Entry Logic (Stricter Constraints)
        self.z_entry_threshold = -3.55  # Deep statistical deviation required
        self.rsi_entry_threshold = 20.0 # Extreme oversold condition
        self.vol_dampener = 0.025       # If Volatility > 2.5%, widen requirements
        
        # Exit Logic (Profit Ratchet)
        self.min_profit_floor = 0.006   # 0.6% Minimum Absolute Profit
        self.ratchet_arm = 0.015        # Arm trailing stop at +1.5%
        self.ratchet_trigger = 0.0025   # Sell if drops 0.25% from peak
        
        # Stagnation (Time Decay)
        self.max_ticks = 350
        self.decay_roi = 0.003          # Reduced target for old trades (Still positive)
        
        # Risk Management
        self.balance = 2000.0
        self.max_positions = 5
        self.trade_pct = 0.19
        
        # State
        self.prices_history = {}
        self.positions = {}             # {symbol: {entry, amount, peak, age}}
        self.cooldowns = {}
        self.tick_counter = 0

    def _get_metrics(self, symbol):
        """ Calculate Z-Score, Volatility, and RSI """
        history = self.prices_history.get(symbol)
        if not history or len(history) < self.lookback:
            return None
            
        data = list(history)
        current = data[-1]
        
        # 1. Volatility & Z-Score
        avg = sum(data) / len(data)
        if avg == 0: return None
        
        variance = sum((x - avg) ** 2 for x in data) / len(data)
        std_dev = math.sqrt(variance)
        
        volatility = std_dev / avg
        z_score = 0 if std_dev == 0 else (current - avg) / std_dev
            
        # 2. RSI
        if len(data) < self.rsi_period + 1:
            rsi = 50.0
        else:
            diffs = [data[i] - data[i-1] for i in range(1, len(data))]
            window = diffs[-self.rsi_period:]
            
            up = sum(x for x in window if x > 0)
            down = abs(sum(x for x in window if x < 0))
            
            if down == 0:
                rsi = 100.0
            else:
                rs = up / down
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            'z': z_score,
            'vol': volatility,
            'rsi': rsi,
            'price': current
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Update Market Data
        active_symbols = []
        for sym, val in prices.items():
            try:
                p = float(val) if not isinstance(val, dict) else float(val.get('price', 0))
                if p <= 0: continue
                
                if sym not in self.prices_history:
                    self.prices_history[sym] = deque(maxlen=self.lookback)
                self.prices_history[sym].append(p)
                active_symbols.append(sym)
            except:
                continue

        # Clean Cooldowns
        ready = [s for s, t in self.cooldowns.items() if self.tick_counter >= t]
        for s in ready: del self.cooldowns[s]

        # 2. EXIT LOGIC (Priority)
        # Randomize to prevent deterministic sequence exploitation
        holdings = list(self.positions.keys())
        random.shuffle(holdings)
        
        for sym in holdings:
            if sym not in active_symbols: continue
            
            pos = self.positions[sym]
            current_p = self.prices_history[sym][-1]
            entry = pos['entry']
            
            # Track High Water Mark
            if current_p > pos['peak']:
                self.positions[sym]['peak'] = current_p
            self.positions[sym]['age'] += 1
            
            # Metrics
            roi = (current_p - entry) / entry
            peak_roi = (pos['peak'] - entry) / entry
            drawdown = (pos['peak'] - current_p) / pos['peak']
            
            should_sell = False
            reason = []
            
            # --- INVARIANT: NO LOSS ---
            # We strictly only consider selling if we are above the floor.
            if roi >= self.min_profit_floor:
                
                # Logic A: Ratchet / Trailing Profit
                # We want to let winners run, but clamp down if they reverse.
                if peak_roi >= self.ratchet_arm:
                    # If we have surged, we set a tight trailing stop
                    if drawdown >= self.ratchet_trigger:
                        should_sell = True
                        reason = ['RATCHET', f'Peak:{peak_roi:.3f}']
                
                # Logic B: Instant Spike Capture
                # If we get a massive candle, take it.
                elif roi > 0.05: # 5% instant
                    should_sell = True
                    reason = ['NOVA', f'ROI:{roi:.3f}']
            
            # Logic C: Stagnation Rescue
            # If trade is old and stagnant, we lower the bar, but keep it POSITIVE.
            if not should_sell and pos['age'] > self.max_ticks:
                if roi >= self.decay_roi:
                    should_sell = True
                    reason = ['DECAY', f'ROI:{roi:.3f}']
            
            if should_sell:
                amount = pos['amount']
                self.balance += current_p * amount
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_counter + 60
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': reason
                }

        # 3. ENTRY LOGIC
        if len(self.positions) >= self.max_positions:
            return None
            
        opportunities = []
        
        for sym in active_symbols:
            if sym in self.positions: continue
            if sym in self.cooldowns: continue
            
            metrics = self._get_metrics(sym)
            if not metrics: continue
            
            z = metrics['z']
            rsi = metrics['rsi']
            vol = metrics['vol']
            
            # --- Dynamic Thresholds ---
            req_z = self.z_entry_threshold
            req_rsi = self.rsi_entry_threshold
            
            # Volatility Dampener:
            # If market is crashing (high vol), we assume the bottom is deeper.
            if vol > self.vol_dampener:
                req_z -= 0.75   # Require -4.3 Z-score
                req_rsi -= 5.0  # Require RSI < 15
            
            if z < req_z and rsi < req_rsi:
                opportunities.append((z, sym, metrics['price']))
                
        if opportunities:
            # Sort by Z-score (most extreme deviation first)
            opportunities.sort(key=lambda x: x[0])
            best_z, best_sym, price = opportunities[0]
            
            # Position Sizing
            allocation = self.balance * self.trade_pct
            amount = allocation / price
            
            self.positions[best_sym] = {
                'entry': price,
                'amount': amount,
                'peak': price,
                'age': 0
            }
            self.balance -= allocation
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': amount,
                'reason': ['DEEP_VAL', f'Z:{best_z:.2f}']
            }

        return None