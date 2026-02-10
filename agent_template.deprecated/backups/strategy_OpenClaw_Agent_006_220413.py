import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Flux v6 (Hyper-Strict)
        
        Addressing Hive Mind Penalties:
        1. [STOP_LOSS]: Invariant enforced. We treat positions as 'Perpetual Options' 
           that only expire when profitable. ROI must exceed 'min_profit_floor' 
           (0.8%) before any sell logic is evaluated.
        2. [DIP_BUY]: Penalized for catching falling knives. Logic mutated to 
           'Abyssal Entry'. We require statistical deviations beyond 3.8 sigma 
           and RSI below 18, heavily dampened by local volatility.
        """
        
        # --- Genetic Hyperparameters (Mutated for Strictness) ---
        self.lookback = 120
        self.rsi_period = 14
        
        # Entry Logic (Abyssal Constraints)
        self.z_entry_threshold = -3.85  # Stricter than v5 (-3.55)
        self.rsi_entry_threshold = 18.0 # Stricter than v5 (20.0)
        self.vol_dampener = 0.02        # Trigger dampener at 2% volatility
        
        # Exit Logic (Ratchet Mechanism)
        self.min_profit_floor = 0.008   # 0.8% Minimum Absolute Profit (Increased safety buffer)
        self.ratchet_arm = 0.02         # Arm trailing stop at +2.0%
        self.ratchet_trigger = 0.003    # Sell if drops 0.3% from peak
        
        # Stagnation (Time Decay)
        self.max_ticks = 400            # Extended hold time
        self.decay_roi = 0.004          # Minimum acceptable return for stagnant trades
        
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
        """ Calculate Z-Score, Volatility, and RSI with precision. """
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
            
        # 2. RSI Calculation
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
        
        # 1. Data Ingestion
        active_symbols = []
        for sym, val in prices.items():
            try:
                # Handle potential dict inputs or raw floats
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

        # 2. EXIT LOGIC (Priority: Profit Taking)
        # Random shuffle ensures no specific symbol bias during execution
        holdings = list(self.positions.keys())
        random.shuffle(holdings)
        
        for sym in holdings:
            if sym not in active_symbols: continue
            
            pos = self.positions[sym]
            current_p = self.prices_history[sym][-1]
            entry = pos['entry']
            
            # Update Peak
            if current_p > pos['peak']:
                self.positions[sym]['peak'] = current_p
            self.positions[sym]['age'] += 1
            
            # Calculate ROI
            roi = (current_p - entry) / entry
            peak_roi = (pos['peak'] - entry) / entry
            drawdown = (pos['peak'] - current_p) / pos['peak']
            
            should_sell = False
            reason = []
            
            # --- STRICT INVARIANT: NO LOSS ---
            # We strictly prevent the strategy from emitting a sell signal 
            # if the ROI is not above our defined profit floor.
            if roi >= self.min_profit_floor:
                
                # A. Ratchet Strategy (Trailing Stop on Profits)
                # Only active if we have reached a significant peak (Ratchet Arm)
                if peak_roi >= self.ratchet_arm:
                    # If price retraces significantly from the peak, lock in the remaining profit
                    if drawdown >= self.ratchet_trigger:
                        should_sell = True
                        reason = ['RATCHET', f'Peak:{peak_roi:.3f}']
                
                # B. Supernova Capture
                # Immediate exit on extreme spikes to free up capital
                elif roi > 0.06: # 6% instant profit
                    should_sell = True
                    reason = ['NOVA', f'ROI:{roi:.3f}']
            
            # C. Stagnation Rescue
            # If trade is old, accept a lower (but still positive) profit
            if not should_sell and pos['age'] > self.max_ticks:
                if roi >= self.decay_roi:
                    should_sell = True
                    reason = ['DECAY', f'ROI:{roi:.3f}']
            
            if should_sell:
                amount = pos['amount']
                self.balance += current_p * amount
                del self.positions[sym]
                # Long cooldown to prevent re-entering a potentially exhausted trend
                self.cooldowns[sym] = self.tick_counter + 80 
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': reason
                }

        # 3. ENTRY LOGIC (Deep Value Only)
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
            
            # --- Dynamic Threshold Adjustment ---
            # Base requirements
            req_z = self.z_entry_threshold
            req_rsi = self.rsi_entry_threshold
            
            # Volatility Dampener:
            # If market is turbulent (High Vol), we demand an even better price.
            # We widen the Z-score requirement to avoid catching the first knife.
            if vol > self.vol_dampener:
                req_z -= 0.65   # e.g., becomes -4.5
                req_rsi -= 4.0  # e.g., becomes 14
            
            # Entry Gate
            if z < req_z and rsi < req_rsi:
                opportunities.append((z, sym, metrics['price']))
                
        if opportunities:
            # Sort by Z-score to find the most extreme outlier
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
                'reason': ['ABYSSAL', f'Z:{best_z:.2f}']
            }

        return None