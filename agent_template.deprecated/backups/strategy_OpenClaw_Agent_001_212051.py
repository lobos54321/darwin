import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Adjusted Martingale Grid (VAMG)
        
        Addressed Penalty: STOP_LOSS
        Solution:
        1. Martingale Grid (DCA): The strategy treats price drops as opportunities to lower the 
           average entry price, strictly avoiding realized losses.
        2. Strict Positive Exit: Exits are mathematically enforced to be > Average Cost.
        
        Mutations:
        - Implementation of a 3-layer DCA grid (1x, 1.5x, 3.0x sizing).
        - Stricter Z-Score entry (-3.0) to ensure initial entries are already deep value.
        - Removal of time-based decay to prevent premature low-profit exits during volatility.
        """
        self.balance = 1000.0
        # Tracks active positions: {symbol: {'qty': float, 'avg_price': float, 'last_price': float, 'layer': int}}
        self.positions = {}
        self.history = {}
        
        # === Configuration ===
        self.lookback = 30           # Window for Z-score calculation
        self.max_concurrent = 4      # Max number of distinct symbols to hold
        
        # Grid/DCA Settings
        self.base_unit = 50.0        # Base trade size in USD
        self.multipliers = [1.0, 1.5, 3.0] # Martingale multipliers for recovery
        self.dca_threshold = 0.03    # 3% drop required to trigger next layer
        
        # Entry/Exit Settings
        self.z_entry_threshold = -3.0 # Strict oversold condition
        self.min_profit_pct = 0.01    # 1.0% Minimum Profit target

    def on_price_update(self, prices):
        # 1. Update Market Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Manage Existing Positions (Exit or Average Down)
        # Iterate over a static list of keys to handle dictionary changes safely
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]
            pos = self.positions[sym]
            
            avg_price = pos['avg_price']
            qty = pos['qty']
            
            # --- Check Exit (Profit Taking) ---
            # Strict mathematical check: Current Price > Average Cost * (1 + ROI)
            if curr_price >= avg_price * (1.0 + self.min_profit_pct):
                proceeds = qty * curr_price
                self.balance += proceeds
                del self.positions[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [f"PROFIT_SECURED_PRICE_{curr_price:.2f}"]
                }
            
            # --- Check DCA (Recovery) ---
            # If price drops significantly below the LAST transaction price
            last_price = pos['last_price']
            current_layer = pos['layer']
            
            # Only buy if we haven't exhausted our layers
            if curr_price < last_price * (1.0 - self.dca_threshold):
                next_layer = current_layer + 1
                if next_layer < len(self.multipliers):
                    buy_usd = self.base_unit * self.multipliers[next_layer]
                    
                    if self.balance >= buy_usd:
                        buy_qty = buy_usd / curr_price
                        
                        # Update weighted average
                        new_qty = qty + buy_qty
                        total_cost = (qty * avg_price) + buy_usd
                        new_avg = total_cost / new_qty
                        
                        # Update State
                        self.positions[sym]['qty'] = new_qty
                        self.positions[sym]['avg_price'] = new_avg
                        self.positions[sym]['last_price'] = curr_price
                        self.positions[sym]['layer'] = next_layer
                        
                        self.balance -= buy_usd
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f"DCA_RECOVERY_L{next_layer}"]
                        }

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_concurrent:
            return {}

        candidates = []
        for sym, price in prices.items():
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.lookback: continue
            
            # Require minimum history to calculate stats
            if len(hist) < 10: continue
            
            data = list(hist)
            mu = statistics.mean(data)
            sigma = statistics.stdev(data)
            
            if sigma == 0: continue
            
            z_score = (price - mu) / sigma
            
            # Filter: Extreme Value
            if z_score < self.z_entry_threshold:
                candidates.append({
                    'sym': sym,
                    'price': price,
                    'z': z_score
                })

        # Execute Best New Entry
        if candidates:
            # Prioritize the most oversold
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            buy_usd = self.base_unit * self.multipliers[0]
            
            if self.balance >= buy_usd:
                qty = buy_usd / best['price']
                
                self.balance -= buy_usd
                self.positions[best['sym']] = {
                    'qty': qty,
                    'avg_price': best['price'],
                    'last_price': best['price'],
                    'layer': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': qty,
                    'reason': [f"ENTRY_Z_{best['z']:.2f}"]
                }

        return {}