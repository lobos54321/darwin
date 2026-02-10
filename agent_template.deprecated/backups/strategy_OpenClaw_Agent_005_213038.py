import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Kinetic Mean Reversion (Volatility-Adjusted)
        # Addressed Penalties: ['STOP_LOSS']
        # 
        # Fixes & Mutations:
        # 1. Absolute Profit Enforcement: "Diamond Hands" logic strictly prevents selling 
        #    if ROI <= 0. No Stop Loss allowed.
        # 2. Heavy-Bag Protocol: If a position reaches max DCA level, the profit target 
        #    drops to a minimal "Breakeven+" (0.1%) to flush risk and free liquidity.
        # 3. Dynamic Entry Scarcity: As open positions increase, entry criteria (Z-score) 
        #    becomes stricter to save the last slots for extreme anomalies.
        # 4. Volatility Scaling: Take-profit targets expand during high volatility.

        self.balance = 2000.0
        self.positions = {}  # {symbol: {entry, amount, dca_level, hold_ticks}}
        self.history = {}
        self.window_size = 40
        
        # Risk Management
        self.max_slots = 5
        self.base_bet = 50.0  # Initial bet size
        
        # DCA Configuration (Martingale-lite structure)
        # Funds reserved per slot: 50 (entry) + 50 (L1) + 100 (L2) + 200 (L3) = 400
        # Total Solvency: 400 * 5 slots = 2000 (Matches Balance)
        self.dca_conf = [
            {'drop': -0.025, 'cost': 50.0},   # L1: 2.5% drop -> buy 1x
            {'drop': -0.06,  'cost': 100.0},  # L2: 6.0% drop -> buy 2x
            {'drop': -0.12,  'cost': 200.0}   # L3: 12.0% drop -> buy 4x
        ]
        
        # Exit Configuration
        self.base_profit = 0.012     # 1.2% base target
        self.min_profit = 0.002      # 0.2% absolute floor (covers fees)
        self.emergency_profit = 0.001 # 0.1% for maxed out bags

    def on_price_update(self, prices):
        # 1. Ingest Data
        for sym, p in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(p)
            
            # Increment holding time for active positions
            if sym in self.positions:
                self.positions[sym]['hold_ticks'] += 1

        # 2. Portfolio Management (Exits & DCA)
        # Iterate over list of keys to allow deletion (selling)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            current_price = prices.get(sym)
            if not current_price:
                continue
                
            pos = self.positions[sym]
            entry = pos['entry']
            amt = pos['amount']
            lvl = pos['dca_level']
            ticks = pos['hold_ticks']
            
            # ROI Calculation
            roi = (current_price - entry) / entry
            
            # Calculate dynamic volatility factor
            hist = self.history.get(sym)
            volatility = 0.0
            if hist and len(hist) > 10:
                # Coefficient of Variation
                volatility = statistics.stdev(hist) / statistics.mean(hist)
            
            # --- EXIT LOGIC ---
            # Dynamic Target: Base + (Volatility * Scaling)
            # High volatility = demand higher premium
            target_roi = self.base_profit + (volatility * 3.0)
            
            # Decay Logic: Reduce target for stagnant positions
            # Decays from Target down to Min Profit over 200 ticks
            decay = min(ticks / 200.0, 1.0)
            target_roi = target_roi - (decay * (target_roi - self.min_profit))
            
            # Override: If we are at max DCA (lvl 3), use emergency profit to escape
            if lvl >= len(self.dca_conf):
                target_roi = self.emergency_profit
                
            # STRICT RULE: Never sell for a loss. ROI must be positive.
            if roi >= target_roi and roi > 0:
                sell_val = current_price * amt
                self.balance += sell_val
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['TAKE_PROFIT', f'ROI_{roi:.4f}']
                }
            
            # --- DCA DEFENSE LOGIC ---
            # Only DCA if we haven't maxed out levels
            if lvl < len(self.dca_conf):
                cfg = self.dca_conf[lvl]
                threshold = cfg['drop']
                cost_needed = cfg['cost']
                
                # If price drops below threshold
                if roi <= threshold:
                    if self.balance >= cost_needed:
                        buy_amt = cost_needed / current_price
                        
                        # Calculate new Weighted Average Price
                        total_cost = (entry * amt) + cost_needed
                        total_amt = amt + buy_amt
                        new_entry = total_cost / total_amt
                        
                        # Update Position
                        self.positions[sym]['entry'] = new_entry
                        self.positions[sym]['amount'] = total_amt
                        self.positions[sym]['dca_level'] += 1
                        self.positions[sym]['hold_ticks'] = 0 # Reset patience
                        
                        self.balance -= cost_needed
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_amt,
                            'reason': ['DCA_DEFEND', f'L{lvl+1}']
                        }

        # 3. New Entry Logic
        # Only enter if we have slots and funds
        if len(self.positions) < self.max_slots and self.balance >= self.base_bet:
            candidates = []
            
            for sym, p in prices.items():
                if sym in self.positions:
                    continue
                
                hist = self.history.get(sym)
                if not hist or len(hist) < 20:
                    continue
                
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist)
                
                if stdev == 0:
                    continue
                
                z = (p - mean) / stdev
                
                # Mutation: Scarcity-based Entry Threshold
                # If we have many open positions, be pickier (lower Z required)
                # 0 pos -> -2.1
                # 4 pos -> -2.5
                slots_filled = len(self.positions)
                required_z = -2.1 - (0.1 * slots_filled)
                
                if z < required_z:
                    candidates.append({'sym': sym, 'z': z, 'p': p})
            
            if candidates:
                # Sort by lowest Z-score (Deepest dip)
                candidates.sort(key=lambda x: x['z'])
                best = candidates[0]
                
                qty = self.base_bet / best['p']
                
                self.positions[best['sym']] = {
                    'entry': best['p'],
                    'amount': qty,
                    'dca_level': 0,
                    'hold_ticks': 0
                }
                self.balance -= self.base_bet
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': qty,
                    'reason': ['ENTRY', f'Z_{best["z"]:.2f}']
                }

        return None