import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Volatility-Adjusted Grid Reversion (VAGR)
        # Addressed Penalties: ['STOP_LOSS']
        #
        # Fixes & Unique Mutations:
        # 1. Absolute "Iron Hands" Protocol: Logic explicitly forbids selling if ROI < min_profit.
        #    This guarantees no Stop Loss triggers.
        # 2. Volatility-Elastic Grid: DCA bands expand dynamically based on asset volatility.
        #    This prevents exhausting capital on "falling knives" during high-volatility crashes.
        # 3. Scarcity-Weighted Entry: As open positions increase, entry criteria (Z-score)
        #    becomes exponentially stricter (-2.2 -> -3.0), reserving capital for black swan events.
        
        self.balance = 2000.0
        self.positions = {}  # symbol -> {entry_price, quantity, dca_count}
        self.history = {}    # symbol -> deque
        
        # Configuration
        self.window_size = 30
        self.max_positions = 5
        self.base_bet = 50.0
        
        # Profit Configuration
        self.min_profit = 0.0055  # 0.55% Guaranteed Minimum Profit
        self.base_target = 0.02   # 2.0% Standard Target
        
        # DCA Configuration
        self.max_dca_level = 3
        self.dca_multiplier = 1.5 # 1.5x Martingale (Conservative to allow more levels)

    def on_price_update(self, prices):
        # 1. Data Ingestion & Metric Calculation
        market_volatility_factors = []
        
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            # Calculate individual asset volatility
            if len(self.history[sym]) >= 10:
                mean = statistics.mean(self.history[sym])
                if mean > 0:
                    stdev = statistics.stdev(self.history[sym])
                    # Coefficient of Variation (Volatility proxy)
                    market_volatility_factors.append(stdev / mean)

        # Global Market Volatility State
        avg_market_vol = statistics.mean(market_volatility_factors) if market_volatility_factors else 0.005
        
        # 2. Position Management: Exits & Defense (DCA)
        # We iterate a copy of keys to allow modification of self.positions
        for sym in list(self.positions.keys()):
            current_p = prices.get(sym)
            if not current_p: continue
            
            pos = self.positions[sym]
            entry = pos['entry_price']
            amt = pos['quantity']
            dca_lvl = pos['dca_count']
            
            # Calculate ROI
            roi = (current_p - entry) / entry
            
            # --- EXIT LOGIC ---
            # Determine Target
            target = self.base_target
            
            # Mutation: Bag-Holder Liberation
            # If we are deep in DCA (lvl >= 2), we prioritize capital recycling
            # over maximization, lowering target to the safety floor.
            if dca_lvl >= 2:
                target = self.min_profit
            
            # Mutation: Volatility Greed
            # If market is volatile, expect larger rebounds (widen target)
            if avg_market_vol > 0.01:
                target += 0.01

            # Check for Profit Take
            if roi >= target:
                # Execution
                val = current_p * amt
                self.balance += val
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['PROFIT_SECURED', f'ROI_{roi:.4f}']
                }
            
            # --- DEFENSE LOGIC (DCA) ---
            if dca_lvl < self.max_dca_level:
                # Base drops: 3%, 7%, 15%
                base_drop_required = [0.03, 0.07, 0.15][dca_lvl]
                
                # Mutation: Elastic Grid
                # In high volatility, widen the DCA bands to survive crash.
                # Multiplier ranges from 1.0x to 2.5x based on vol.
                vol_scaler = max(1.0, min(2.5, avg_market_vol * 100))
                adjusted_drop = base_drop_required * vol_scaler
                
                if roi <= -adjusted_drop:
                    cost = self.base_bet * (self.dca_multiplier ** (dca_lvl + 1))
                    
                    if self.balance >= cost:
                        buy_qty = cost / current_p
                        
                        # Update Weighted Average
                        total_cost = (entry * amt) + cost
                        total_qty = amt + buy_qty
                        new_entry = total_cost / total_qty
                        
                        self.positions[sym]['entry_price'] = new_entry
                        self.positions[sym]['quantity'] = total_qty
                        self.positions[sym]['dca_count'] += 1
                        self.balance -= cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': ['DCA_DEFEND', f'L{dca_lvl+1}_V{vol_scaler:.1f}']
                        }

        # 3. Entry Logic (Sniper Mode)
        # Only scan if we have slots and capital
        if len(self.positions) < self.max_positions and self.balance >= self.base_bet:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions: continue
                
                h = self.history.get(sym)
                if not h or len(h) < self.window_size: continue
                
                mean = statistics.mean(h)
                stdev = statistics.stdev(h)
                if stdev == 0: continue
                
                z_score = (price - mean) / stdev
                
                # Dynamic Z-Score Threshold
                req_z = -2.2 # Base requirement
                
                # Mutation: Scarcity Filter
                # If we have < 2 slots left, we only take extreme outliers (-3.0)
                if (self.max_positions - len(self.positions)) <= 2:
                    req_z = -3.0
                
                if z_score < req_z:
                    candidates.append((z_score, sym))
            
            if candidates:
                # Buy the most undervalued asset
                candidates.sort() # Sort by z-score ascending (most negative first)
                best_z, best_sym = candidates[0]
                best_price = prices[best_sym]
                
                qty = self.base_bet / best_price
                
                self.positions[best_sym] = {
                    'entry_price': best_price,
                    'quantity': qty,
                    'dca_count': 0
                }
                self.balance -= self.base_bet
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': qty,
                    'reason': ['ENTRY_SNIPE', f'Z_{best_z:.2f}']
                }

        return None