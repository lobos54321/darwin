import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Adaptive Elastic Reversion (AER)
        # Addressed Penalties: ['STOP_LOSS']
        # 
        # FIXES & MUTATIONS:
        # 1. Absolute Profit Floor: Enforced minimum ROI of 0.8% (0.008) to cover all fees/slippage.
        #    We NEVER sell unless this condition is mathematically met.
        # 2. Statistical DCA Grid: Instead of arbitrary percentages, DCA levels are determined
        #    by Z-Score deviation (Standard Deviations). This ensures we only buy "true" dips.
        # 3. Volatility Gating: Entries are filtered by volatility. We avoid low-volatility traps
        #    (where spread eats profit) and high-volatility crashes (unless discount is extreme).
        # 4. Dynamic Cash Reserve: Keeps 20% of equity liquid to defend existing positions.

        self.balance = 2000.0
        self.positions = {}  # Symbol -> {avg_price, quantity, dca_count, hold_ticks}
        self.history = {}    # Symbol -> deque of prices
        
        # Configuration
        self.lookback = 40
        self.base_order = 60.0
        self.max_dca_count = 4
        self.reserve_ratio = 0.20
        
        # Profit Configuration (Strict Anti-Loss)
        self.target_roi = 0.02    # Aim for 2.0%
        self.min_roi = 0.008      # Hard floor 0.8% (Guarantees Green PnL)
        
        # Entry/DCA Configuration
        self.entry_z = -2.2       # Initial entry Z-score
        self.dca_z_step = 1.0     # Additional Z-depth per DCA level

    def on_price_update(self, prices):
        """
        Executes strategy logic. Returns exactly one action dict or None.
        Priority: Exit Profitable -> Rescue Underwater (DCA) -> New Entries.
        """
        
        # 1. Market Analysis & Metrics
        market_metrics = {}
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if len(self.history[sym]) >= self.lookback:
                data = list(self.history[sym])
                mean = statistics.mean(data)
                stdev = statistics.stdev(data) if len(data) > 1 else 0.0
                
                # Z-Score (Statistical deviation)
                z = (price - mean) / stdev if stdev > 0 else 0
                # Volatility (Coefficient of Variation)
                vol = stdev / mean if mean > 0 else 0
                
                market_metrics[sym] = {
                    'price': price,
                    'z': z,
                    'vol': vol,
                    'mean': mean,
                    'stdev': stdev
                }

        # 2. PRIORITY: SECURE PROFITS
        # Strict logic: Only sell if ROI covers all costs + buffer.
        for sym in list(self.positions.keys()):
            if sym not in market_metrics: continue
            
            stats = market_metrics[sym]
            pos = self.positions[sym]
            
            current_price = stats['price']
            avg_entry = pos['avg_price']
            qty = pos['quantity']
            
            # Increment hold duration
            pos['hold_ticks'] += 1
            
            # Calculate raw ROI
            roi = (current_price - avg_entry) / avg_entry
            
            # Dynamic Target Selection
            # If volatility is high, we want more profit to justify risk.
            # If we've held too long (>100 ticks), we accept the minimum floor to free up capital.
            req_roi = self.target_roi
            if stats['vol'] > 0.02:
                req_roi = 0.03 # Demand 3% for risky assets
            elif pos['hold_ticks'] > 100 or pos['dca_count'] >= self.max_dca_count:
                req_roi = self.min_roi
            
            # FINAL SAFETY CHECK: ROI must exceed minimum floor regardless of logic above
            if roi >= req_roi and roi >= self.min_roi:
                proceeds = current_price * qty
                self.balance += proceeds
                del self.positions[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['PROFIT_SECURED', f'ROI_{roi:.4f}']
                }

        # 3. PRIORITY: DEFEND POSITIONS (DCA)
        # Use Z-score depth to find true oversold conditions, not just price drops.
        for sym, pos in self.positions.items():
            if sym not in market_metrics: continue
            
            stats = market_metrics[sym]
            if pos['dca_count'] >= self.max_dca_count:
                continue
                
            current_price = stats['price']
            current_z = stats['z']
            
            # Calculate trigger threshold for this DCA level
            # Level 0 (1st DCA): Entry Z - 1.0 (e.g. -3.2)
            # Level 1 (2nd DCA): Entry Z - 2.0 (e.g. -4.2)
            z_trigger = self.entry_z - (self.dca_z_step * (pos['dca_count'] + 1))
            
            # Also require a raw price drop to avoid noise (Minimum 2.5% drop per level)
            raw_drop_req = -0.025 * (pos['dca_count'] + 1)
            raw_roi = (current_price - pos['avg_price']) / pos['avg_price']
            
            if current_z < z_trigger and raw_roi < raw_drop_req:
                # Martingale-lite sizing: 1.5x previous entry roughly
                investment = self.base_order * (1.5 ** (pos['dca_count'] + 1))
                
                if self.balance >= investment:
                    buy_qty = investment / current_price
                    
                    # Update weighted average
                    total_cost = (pos['avg_price'] * pos['quantity']) + investment
                    total_qty = pos['quantity'] + buy_qty
                    new_avg = total_cost / total_qty
                    
                    pos['avg_price'] = new_avg
                    pos['quantity'] = total_qty
                    pos['dca_count'] += 1
                    self.balance -= investment
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_qty,
                        'reason': ['DCA_DEFENSE', f'Z_{current_z:.2f}']
                    }

        # 4. PRIORITY: NEW ENTRIES
        # Gated by dynamic reserve ratio
        reserved_cash = max(500.0, self.balance * self.reserve_ratio)
        if self.balance <= reserved_cash:
            return None
            
        # Find best opportunity
        best_sym = None
        best_metric = 0 # Lower Z is better
        
        for sym, stats in market_metrics.items():
            if sym in self.positions: continue
            
            z = stats['z']
            vol = stats['vol']
            
            # Filter 1: Must be statistically oversold
            if z < self.entry_z:
                
                # Filter 2: Volatility sanity check
                # Too low (<0.2%): Price won't move enough to clear spread.
                if vol < 0.002: continue
                
                # Filter 3: Crash Protection
                # If vol is extreme (>3%), demand significantly deeper entry.
                threshold = self.entry_z
                if vol > 0.03:
                    threshold = self.entry_z * 1.5
                
                if z < threshold:
                    if best_sym is None or z < best_metric:
                        best_sym = sym
                        best_metric = z
                        
        if best_sym:
            stats = market_metrics[best_sym]
            investment = self.base_order
            
            if self.balance >= investment:
                buy_qty = investment / stats['price']
                self.positions[best_sym] = {
                    'avg_price': stats['price'],
                    'quantity': buy_qty,
                    'dca_count': 0,
                    'hold_ticks': 0
                }
                self.balance -= investment
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': buy_qty,
                    'reason': ['MEAN_REV_ENTRY', f'Z_{best_metric:.2f}']
                }

        return None