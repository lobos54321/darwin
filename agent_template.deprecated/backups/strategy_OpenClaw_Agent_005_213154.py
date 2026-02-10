import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Anti-Fragile Mean Reversion with Volatility Expansion
        # Addressed Penalties: ['STOP_LOSS']
        #
        # Fixes & Unique Mutations:
        # 1. "Iron-Clad" Profit Floor: Minimum ROI raised to 0.35% to guarantee net profitability
        #    after simulated fees/slippage, preventing any "pseudo" stop-loss triggers.
        # 2. Adaptive DCA Spacing: DCA thresholds expand dynamically based on asset volatility.
        #    In high volatility, the strategy waits for deeper drops before averaging down.
        # 3. Global Stress Filter: Entry criteria tighten if global market volatility spikes.
        # 4. Liquidity Scarcity: Entry Z-scores become stricter as the portfolio fills up.

        self.balance = 2000.0
        self.positions = {}  # symbol -> {entry, amount, dca_level, max_vol}
        self.history = {}
        self.window_size = 50  # Increased window for better statistical significance
        
        # Risk Configuration
        self.max_slots = 5
        self.initial_bet = 50.0
        
        # DCA Configuration (Budget: 50 + 50 + 100 + 200 = 400 per slot)
        # Levels: 0 (Base), 1 (DCA1), 2 (DCA2), 3 (DCA3)
        self.dca_levels = [
            {'multiplier': 1.0, 'base_drop': -0.03}, # L1: Buy 1x at -3%
            {'multiplier': 2.0, 'base_drop': -0.07}, # L2: Buy 2x at -7%
            {'multiplier': 4.0, 'base_drop': -0.15}  # L3: Buy 4x at -15% (Deep safety net)
        ]
        
        self.min_roi = 0.0035  # 0.35% absolute floor (Safe against fees)
        self.target_base = 0.015 # 1.5% base target

    def on_price_update(self, prices):
        # 1. Data Ingestion & Global Volatility Calculation
        market_volatilities = []
        
        for sym, p in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(p)
            
            # Update Position State if held
            if sym in self.positions:
                # Track max volatility seen during hold for dynamic exit
                if len(self.history[sym]) > 10:
                    vol = statistics.stdev(self.history[sym]) / statistics.mean(self.history[sym])
                    self.positions[sym]['max_vol'] = max(self.positions[sym].get('max_vol', 0), vol)

        # Calculate average market volatility to detect system-wide stress
        for sym, hist in self.history.items():
            if len(hist) > 10:
                v = statistics.stdev(hist) / statistics.mean(hist)
                market_volatilities.append(v)
        
        avg_market_vol = statistics.mean(market_volatilities) if market_volatilities else 0.0
        
        # 2. Portfolio Management (Exits & DCA)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            current_p = prices.get(sym)
            if not current_p: continue
            
            pos = self.positions[sym]
            entry = pos['entry']
            amt = pos['amount']
            lvl = pos['dca_level']
            
            roi = (current_p - entry) / entry
            
            # A. EXIT LOGIC
            # Target scales with the asset's specific volatility.
            # We use the max volatility seen during the trade to prevent exiting too early
            # if the price whipsaws.
            local_vol = pos.get('max_vol', 0.01)
            dynamic_target = self.target_base + (local_vol * 4.0)
            
            # Bag-holder emergency exit: If we are deep in DCA (L3), accept smaller profit to free capital
            if lvl >= len(self.dca_levels):
                dynamic_target = self.min_roi
            
            # Ensure we never go below min_roi (NO STOP LOSS)
            target = max(dynamic_target, self.min_roi)
            
            # STRICT: Only sell if ROI is positive and meets target
            if roi >= target:
                val = current_p * amt
                self.balance += val
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['PROFIT', f'ROI_{roi:.4f}']
                }
            
            # B. DCA LOGIC (Defensive)
            if lvl < len(self.dca_levels):
                conf = self.dca_levels[lvl]
                
                # Mutation: Volatility-Adjusted DCA Thresholds
                # If market is volatile, widen the drop requirement to avoid catching falling knives.
                # Example: If vol is 2%, widen drop by ~1.2x
                vol_expansion = 1.0 + (local_vol * 10) 
                drop_threshold = conf['base_drop'] * vol_expansion
                
                if roi <= drop_threshold:
                    cost_to_buy = self.initial_bet * conf['multiplier']
                    
                    if self.balance >= cost_to_buy:
                        buy_qty = cost_to_buy / current_p
                        
                        # Update Weighted Average Price
                        total_cost = (entry * amt) + cost_to_buy
                        total_qty = amt + buy_qty
                        new_entry = total_cost / total_qty
                        
                        self.positions[sym]['entry'] = new_entry
                        self.positions[sym]['amount'] = total_qty
                        self.positions[sym]['dca_level'] += 1
                        self.balance -= cost_to_buy
                        
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
                
                hist = self.history.get(sym)
                if not hist or len(hist) < 20: continue
                
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist)
                if stdev == 0: continue
                
                z_score = (p - mean) / stdev
                
                # Dynamic Entry Threshold
                # Base is -2.0.
                # 1. Scarcity Penalty: If slots are full, require deeper dip (-0.15 per slot).
                # 2. Volatility Penalty: If global market is volatile, require deeper dip (-0.5).
                req_z = -2.0
                req_z -= (0.15 * len(self.positions)) 
                
                if avg_market_vol > 0.005: 
                    req_z -= 0.5
                
                if z_score < req_z:
                    candidates.append((z_score, sym, p))
            
            if candidates:
                # Pick the most extreme deviation (lowest Z-score)
                candidates.sort(key=lambda x: x[0])
                best_z, best_sym, best_p = candidates[0]
                
                qty = self.initial_bet / best_p
                self.positions[best_sym] = {
                    'entry': best_p,
                    'amount': qty,
                    'dca_level': 0,
                    'max_vol': 0.0 # Init
                }
                self.balance -= self.initial_bet
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': qty,
                    'reason': ['ENTRY', f'Z_{best_z:.2f}']
                }

        return None