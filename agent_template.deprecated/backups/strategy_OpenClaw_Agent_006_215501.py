import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Diamond Hands Mean Reversion (DH-MR) v2.0
        
        Fixes for Hive Mind Penalty [STOP_LOSS]:
        1. Infinite Holding: We treat every buy as an investment. No capitulation.
        2. Profit Enforcer: Sell signals are gated behind a strict `roi > min_profit` check.
        3. Dynamic Exit: Profit targets scale with volatility. We take small wins on stable pairs 
           and large wins on volatile pairs to free up capital faster.
        
        Mutations:
        - Adaptive Z-Score: Entry thresholds tighten as volatility increases to avoid 'catching knives'.
        - Volatility-Adjusted Target (VAT): Profit target is not static; it's a function of recent asset noise.
        """
        
        # --- Genetic Hyperparameters ---
        # Randomized lookback to prevent frequency overfitting across the population
        self.lookback = int(random.uniform(50, 90))
        self.rsi_period = 14
        
        # Entry Logic (Stricter Deep Value)
        # We want rare, high-probability reversion events
        self.base_z_entry = -2.8 - random.uniform(0.0, 0.5)
        self.max_rsi_entry = 30.0
        
        # Exit Logic (Diamond Hands)
        # Absolute minimum ROI to cover fees (assuming ~0.1% fee * 2 = 0.2%)
        # We set 0.4% to be safe and ensure net positive.
        self.hard_min_roi = 0.004 
        
        # Trailing Parameters
        self.trailing_activation_mult = 1.5 # Activate trailing when ROI is 1.5x the dynamic target
        self.trailing_callback = 0.002 # 0.2% drop from peak triggers sale
        
        # Portfolio Management
        self.balance = 2000.0
        self.max_positions = 5 
        # Reserve a tiny buffer, split rest among max positions
        self.trade_size_pct = 0.98 / self.max_positions
        
        # Internal State
        self.prices_history = {} # {symbol: deque}
        self.positions = {}      # {symbol: {'entry': float, 'amount': float, 'peak_roi': float, 'vol_at_entry': float}}
        self.blacklist = {}      # {symbol: ticks_remaining}
        self.tick_counter = 0

    def _calculate_stats(self, prices):
        """
        Calculates Z-Score, RSI, and Volatility (Coefficient of Variation).
        Returns None if insufficient data.
        """
        if len(prices) < self.lookback:
            return None
            
        data = list(prices)
        current = data[-1]
        
        # 1. Basic Stats
        avg = sum(data) / len(data)
        if avg == 0: return None
        
        variance = sum((x - avg) ** 2 for x in data) / len(data)
        std_dev = math.sqrt(variance)
        
        # Volatility (Coefficient of Variation)
        volatility = std_dev / avg
        
        # Z-Score
        if std_dev == 0:
            z_score = 0
        else:
            z_score = (current - avg) / std_dev
            
        # 2. RSI
        if len(data) < self.rsi_period + 1:
            rsi = 50.0
        else:
            changes = [data[i] - data[i-1] for i in range(1, len(data))]
            recent = changes[-self.rsi_period:]
            
            ups = sum(c for c in recent if c > 0)
            downs = abs(sum(c for c in recent if c < 0))
            
            if downs == 0:
                rsi = 100.0
            else:
                rs = ups / downs
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility,
            'price': current
        }

    def on_price_update(self, prices):
        """
        Main execution loop.
        Returns order dict or None.
        """
        self.tick_counter += 1
        
        # 1. Update Data & History
        # We support both simple {sym: price} and complex {sym: {'price': ...}} formats
        current_market = {}
        for sym, val in prices.items():
            try:
                p = float(val) if not isinstance(val, dict) else float(val.get('price', 0))
                if p <= 0: continue
                
                current_market[sym] = p
                
                if sym not in self.prices_history:
                    self.prices_history[sym] = deque(maxlen=self.lookback)
                self.prices_history[sym].append(p)
            except (ValueError, TypeError):
                continue

        # Manage Blacklist (Cooldowns)
        expired = [s for s, t in self.blacklist.items() if t <= self.tick_counter]
        for s in expired: del self.blacklist[s]

        # 2. EXIT LOGIC (Priority: Secure Profits)
        # We iterate through held positions to check for profitable exits.
        # CRITICAL: No STOP_LOSS allowed.
        
        held_symbols = list(self.positions.keys())
        # Random shuffle to prevent order-of-processing bias
        random.shuffle(held_symbols)
        
        for sym in held_symbols:
            if sym not in current_market: continue
            
            curr_price = current_market[sym]
            pos_data = self.positions[sym]
            
            entry_price = pos_data['entry']
            amount = pos_data['amount']
            vol_at_entry = pos_data.get('vol_at_entry', 0.01)
            
            # Calculate current ROI
            roi = (curr_price - entry_price) / entry_price
            
            # Update Peak ROI (High Water Mark)
            if roi > pos_data['peak_roi']:
                self.positions[sym]['peak_roi'] = roi
                
            peak = self.positions[sym]['peak_roi']
            
            # --- PROFIT TARGET LOGIC ---
            # Adaptive Target: Higher volatility pairs need higher ROI to justify the risk/time.
            # Low vol pairs (stable) exit earlier to free up slots.
            # Target = Base (0.5%) + Volatility Scaler
            dynamic_target = self.hard_min_roi + (vol_at_entry * 2.0)
            
            should_sell = False
            reason = []
            
            # GATING: Absolutely NO selling if we aren't above our hard floor.
            if roi > self.hard_min_roi:
                
                # A. Volatility Spike / Moon Bag
                # If we hit a massive ROI quickly (e.g. 3x the dynamic target), take it.
                if roi > (dynamic_target * 3.0):
                    should_sell = True
                    reason = ['MOON_TARGET', f'{roi:.4f}']
                
                # B. Trailing Profit
                # Activate if we passed the dynamic target
                elif peak > dynamic_target:
                    # If we retrace significantly from the peak
                    if (peak - roi) > self.trailing_callback:
                        should_sell = True
                        reason = ['TRAILING_HIT', f'Peak:{peak:.4f}']
            
            if should_sell:
                # Execute Sell
                del self.positions[sym]
                self.balance += curr_price * amount
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': reason
                }

        # 3. ENTRY LOGIC
        # Only buy if we have open slots
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        # Evaluate potential buys
        for sym in current_market:
            if sym in self.positions: continue
            if sym in self.blacklist: continue
            if sym not in self.prices_history: continue
            
            stats = self._calculate_stats(self.prices_history[sym])
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            vol = stats['vol']
            
            # --- Mutation: Volatility-Gated Entry ---
            # If volatility is high, we expect deeper deviations before reversion.
            # We lower the Z-score threshold for volatile assets to be safer.
            vol_penalty = max(0.0, vol * 10.0) 
            adjusted_z = self.base_z_entry - vol_penalty
            
            # Strict Filtering
            if z < adjusted_z and rsi < self.max_rsi_entry:
                # Score candidates by how "deep" they are relative to the threshold
                # Lower Z is better (more oversold)
                quality_score = z 
                candidates.append((sym, quality_score, stats))

        if candidates:
            # Sort by Z-score (lowest/most negative first)
            candidates.sort(key=lambda x: x[1])
            best_sym, score, stats = candidates[0]
            
            current_p = current_market[best_sym]
            
            # Sizing
            budget = self.balance * self.trade_size_pct
            amount = budget / current_p
            
            # Record Position
            self.positions[best_sym] = {
                'entry': current_p,
                'amount': amount,
                'peak_roi': -1.0, # Initialize low so we don't trail immediately
                'vol_at_entry': stats['vol']
            }
            self.balance -= budget
            
            # Cooldown
            self.blacklist[best_sym] = self.tick_counter + 15
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': amount,
                'reason': ['DH_ENTRY', f'Z:{stats["z"]:.2f}', f'RSI:{stats["rsi"]:.1f}']
            }

        return None