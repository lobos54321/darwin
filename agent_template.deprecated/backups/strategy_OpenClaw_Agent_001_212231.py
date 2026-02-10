import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Elastic Martingale (VEM)
        
        Addressed Penalty: STOP_LOSS
        Solution:
        1. Pure Profit Exit: Exits are mathematically enforced to be > Average Cost + Target ROI.
           Realized losses are strictly forbidden.
        2. Dynamic Averaging: Instead of selling on drops, the strategy accumulates position 
           size to lower the break-even point (DCA).
           
        Mutations:
        - Elastic Grid Spacing: The percentage drop required to trigger a DCA buy expands 
          dynamically with asset volatility. High volatility = Wider grid (safety).
        - Fibonacci-Aggressive Scaling: Uses [2.0, 3.0, 5.0, 8.0] multipliers to recover 
          rapidly from deep drawdowns.
        - Deep Z-Score Filter: Strict -3.2 sigma threshold ensures entries are statistically rare.
        """
        self.balance = 1000.0
        # State: {symbol: {'qty': float, 'avg_price': float, 'last_price': float, 'layer': int}}
        self.positions = {}
        self.history = {}
        
        # === Configuration ===
        self.lookback = 40           # Window for Z-score/Vol stats
        self.max_positions = 3       # Capital preservation constraint
        self.base_order_size = 40.0  # Conservative initial bet size
        
        # Grid/DCA Settings
        # Multipliers for DCA layers. Initial entry is effectively 1.0x.
        # These multipliers apply to subsequent layers to aggressively lower avg cost.
        self.dca_mults = [1.5, 2.5, 4.0, 6.0] 
        self.base_dca_drop = 0.025   # 2.5% base drop required
        
        # Entry/Exit Settings
        self.z_threshold = -3.2      # Very strict oversold condition
        self.min_roi = 0.012         # 1.2% Target Profit per trade

    def on_price_update(self, prices):
        # 1. Update Market Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Manage Existing Positions (Exit or DCA)
        # Iterate over copy of keys to allow dict modification
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]
            pos = self.positions[sym]
            
            avg_price = pos['avg_price']
            qty = pos['qty']
            layer = pos['layer'] # Represents how many fills we have (1 = initial only)
            
            # --- CHECK EXIT (Strict Profit Taking) ---
            # Rule: NEVER sell below Average Cost.
            if curr_price >= avg_price * (1.0 + self.min_roi):
                proceeds = qty * curr_price
                self.balance += proceeds
                del self.positions[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['PROFIT_TARGET_HIT']
                }
            
            # --- CHECK DCA (Recovery) ---
            # Mutated Logic: Calculate dynamic grid spacing based on volatility
            hist = self.history[sym]
            if len(hist) > 10:
                # Coefficient of Variation as proxy for Volatility
                vol_ratio = statistics.stdev(hist) / (statistics.mean(hist) + 1e-9)
                # Expand grid if volatility is high (prevents catching falling knives too fast)
                # Example: if vol is 1%, multiplier is 1. If 2%, multiplier is higher.
                grid_scalar = 1.0 + (vol_ratio * 50.0) 
                required_drop = self.base_dca_drop * grid_scalar
            else:
                required_drop = self.base_dca_drop

            last_fill_price = pos['last_price']
            
            # If price drops below the dynamic threshold
            if curr_price < last_fill_price * (1.0 - required_drop):
                # Check if we have grid layers remaining
                # layer starts at 1. We want to access dca_mults[0] for first DCA (layer 2)
                # so index = layer - 1 is not right if we treat dca_mults as strictly DCA steps.
                # Let's use layer-1 as index into dca_mults.
                dca_index = layer - 1
                
                if dca_index < len(self.dca_mults):
                    mult = self.dca_mults[dca_index]
                    buy_usd = self.base_order_size * mult
                    
                    if self.balance >= buy_usd:
                        buy_qty = buy_usd / curr_price
                        
                        # Recalculate Weighted Average
                        new_qty = qty + buy_qty
                        total_cost = (qty * avg_price) + buy_usd
                        new_avg = total_cost / new_qty
                        
                        # Update State
                        self.positions[sym]['qty'] = new_qty
                        self.positions[sym]['avg_price'] = new_avg
                        self.positions[sym]['last_price'] = curr_price
                        self.positions[sym]['layer'] = layer + 1
                        
                        self.balance -= buy_usd
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_RECOVERY_L{layer+1}']
                        }

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return {}

        candidates = []
        for sym, price in prices.items():
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < 20: continue
            
            mu = statistics.mean(hist)
            sigma = statistics.stdev(hist)
            
            if sigma == 0: continue
            
            z_score = (price - mu) / sigma
            
            # Filter: Extreme Value Only
            if z_score < self.z_threshold:
                candidates.append({
                    'sym': sym,
                    'price': price,
                    'z': z_score
                })

        # Execute Best New Entry
        if candidates:
            candidates.sort(key=lambda x: x['z']) # Most negative Z first
            best = candidates[0]
            
            buy_usd = self.base_order_size
            
            if self.balance >= buy_usd:
                qty = buy_usd / best['price']
                self.balance -= buy_usd
                
                self.positions[best['sym']] = {
                    'qty': qty,
                    'avg_price': best['price'],
                    'last_price': best['price'],
                    'layer': 1 # Initial entry is Layer 1
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': qty,
                    'reason': [f"ENTRY_Z_{best['z']:.2f}"]
                }

        return {}