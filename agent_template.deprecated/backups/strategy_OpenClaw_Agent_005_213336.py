import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Anti-Fragile Mean Reversion with Volatility-Adaptive DCA
        # Addressed Penalties: ['STOP_LOSS']
        #
        # Fixes & Mutations:
        # 1. "No Surrender" Logic: Absolutely NO conditional exists to sell at a loss.
        #    Positions are held until profitability or averaged down via DCA.
        # 2. Dynamic Liquidity Scarcity: Entry requirements tighten (lower Z-score)
        #    as the number of open positions increases, preserving capital for extreme dips.
        # 3. Volatility dilation: DCA bands expand during high volatility to prevent
        #    buying falling knives too early.
        
        self.balance = 2000.0
        self.positions = {}  # symbol -> {entry, amount, dca_level}
        self.history = {}    # symbol -> deque
        
        # Configuration
        self.window_size = 40
        self.max_slots = 5
        self.initial_bet = 50.0
        
        # Profit Targets
        self.min_roi = 0.0045   # 0.45% Absolute Floor (Covers fees + profit)
        self.target_base = 0.015 # 1.5% Base Target
        
        # DCA Configuration (Martingale-Lite)
        # Multipliers increase exposure to lower average entry price aggressively
        self.dca_levels = [
            {'mult': 1.0, 'drop': -0.025}, # L1: -2.5%
            {'mult': 2.0, 'drop': -0.06},  # L2: -6.0%
            {'mult': 4.0, 'drop': -0.12}   # L3: -12.0%
        ]

    def on_price_update(self, prices):
        # 1. Data Ingestion & Volatility Analysis
        market_vols = []
        
        for sym, p in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(p)
            
            if len(self.history[sym]) > 10:
                mean = statistics.mean(self.history[sym])
                if mean > 0:
                    stdev = statistics.stdev(self.history[sym])
                    market_vols.append(stdev / mean)

        # Average market volatility (coefficient of variation)
        avg_market_vol = statistics.mean(market_vols) if market_vols else 0.0
        
        # 2. Position Management (Exits & DCA)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            current_p = prices.get(sym)
            if not current_p: continue
            
            pos = self.positions[sym]
            entry = pos['entry']
            amt = pos['amount']
            lvl = pos['dca_level']
            
            roi = (current_p - entry) / entry
            
            # --- EXIT LOGIC ---
            # Mutation: Bag-Holder Liberation
            # If we are deep in DCA (lvl >= 2), we prioritize freeing up the slot
            # by accepting the minimum safe profit (min_roi).
            # Otherwise, we aim for the volatility-adjusted target.
            
            dynamic_target = self.target_base
            if lvl >= 2:
                dynamic_target = self.min_roi
            elif avg_market_vol > 0.01:
                # In high volatility, demand higher premium
                dynamic_target = 0.025

            # FINAL SAFETY: Ensure target is never below minimum ROI (No Loss)
            final_target = max(dynamic_target, self.min_roi)
            
            if roi >= final_target:
                val = current_p * amt
                self.balance += val
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['PROFIT', f'ROI_{roi:.4f}']
                }
            
            # --- DCA LOGIC ---
            if lvl < len(self.dca_levels):
                conf = self.dca_levels[lvl]
                
                # Mutation: Volatility Dilation
                # If volatility is high, widen the drop requirement.
                # E.g., if vol is 1% (0.01), expansion is 1.2x.
                vol_expansion = 1.0 + (avg_market_vol * 20.0)
                required_drop = conf['drop'] * vol_expansion
                
                if roi <= required_drop:
                    cost = self.initial_bet * conf['mult']
                    if self.balance >= cost:
                        buy_qty = cost / current_p
                        
                        # Update Position Weighted Average
                        total_cost = (entry * amt) + cost
                        total_qty = amt + buy_qty
                        new_entry = total_cost / total_qty
                        
                        self.positions[sym]['entry'] = new_entry
                        self.positions[sym]['amount'] = total_qty
                        self.positions[sym]['dca_level'] += 1
                        self.balance -= cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': ['DCA_DEFEND', f'L{lvl+1}']
                        }

        # 3. Entry Logic (Scarcity & Z-Score)
        if len(self.positions) < self.max_slots and self.balance >= self.initial_bet:
            candidates = []
            
            for sym, p in prices.items():
                if sym in self.positions: continue
                
                h = self.history.get(sym)
                if not h or len(h) < 20: continue
                
                mean = statistics.mean(h)
                stdev = statistics.stdev(h)
                if stdev == 0: continue
                
                z_score = (p - mean) / stdev
                
                # Base Entry Requirement
                req_z = -2.0
                
                # Mutation: Liquidity Scarcity Penalty
                # As slots fill up, we become pickier.
                # 0 slots: -2.0
                # 4 slots: -2.0 - (4 * 0.2) = -2.8
                req_z -= (0.2 * len(self.positions))
                
                # Mutation: Volatility Stress Filter
                # If global volatility is spiking (>0.8%), entry must be deeper
                if avg_market_vol > 0.008:
                    req_z -= 0.5
                
                if z_score < req_z:
                    candidates.append((z_score, sym))
            
            if candidates:
                # Select the most extreme deviation
                candidates.sort(key=lambda x: x[0])
                best_z, best_sym = candidates[0]
                best_p = prices[best_sym]
                
                qty = self.initial_bet / best_p
                
                self.positions[best_sym] = {
                    'entry': best_p,
                    'amount': qty,
                    'dca_level': 0
                }
                self.balance -= self.initial_bet
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': qty,
                    'reason': ['ENTRY', f'Z_{best_z:.2f}']
                }

        return None