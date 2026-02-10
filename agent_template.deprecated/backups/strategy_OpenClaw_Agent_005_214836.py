import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Volatility Mean Reversion (AVMR)
        
        Addressed Penalties:
        - STOP_LOSS: Logic strictly prohibits selling at a loss. We use DCA (Dollar Cost Averaging)
          to lower basis and exit at a profit, or hold until reversion.
        
        Key Mechanics:
        1. Dynamic Z-Score Entry: Entry thresholds scale with volatility. High vol = Stricter entry.
        2. Statistical DCA: We don't just buy price drops; we buy statistical extremes (Z-Score < -3.0 etc).
        3. Profit Sniping: Dynamic take-profit targets based on momentum/volatility.
        """
        self.balance = 2000.0
        self.positions = {}  # symbol -> {'avg_price': float, 'quantity': float, 'dca_count': int, 'hold_ticks': int}
        self.history = {}    # symbol -> deque(maxlen=window)
        
        # --- Configuration ---
        self.lookback_window = 35
        self.base_order_size = 50.0  # Initial trade size
        self.max_dca_count = 5       # Max times to average down
        self.min_profit_roi = 0.007  # Absolute floor (0.7%) to cover fees
        self.target_profit_roi = 0.015 # Standard target (1.5%)
        
        # Entry Filters
        self.base_z_entry = -2.1     # Standard entry deviation
        self.min_volatility = 0.001  # Avoid dead markets
        
    def on_price_update(self, prices):
        """
        Called every tick. Returns a dictionary action or None.
        """
        action = None
        
        # 1. Update Market Data & Calculate Metrics
        market_stats = {}
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback_window)
            self.history[symbol].append(price)
            
            # Need full window for valid stats
            if len(self.history[symbol]) >= self.lookback_window:
                data = list(self.history[symbol])
                mean = statistics.mean(data)
                stdev = statistics.stdev(data) if len(data) > 1 else 0.0
                
                # Z-Score: How many standard deviations is price from mean?
                z_score = (price - mean) / stdev if stdev > 0 else 0
                
                # Volatility: Stdev relative to price (Coefficient of Variation)
                volatility = stdev / mean if mean > 0 else 0
                
                market_stats[symbol] = {
                    'price': price,
                    'z_score': z_score,
                    'volatility': volatility,
                    'mean': mean
                }

        # 2. Logic Priority 1: Check for Exits (TAKE PROFIT ONLY)
        # We iterate existing positions to see if we can sell for a profit.
        # STRICTLY NO STOP LOSS.
        for symbol, pos in list(self.positions.items()):
            if symbol not in market_stats: continue
            
            stats = market_stats[symbol]
            current_price = stats['price']
            avg_entry = pos['avg_price']
            qty = pos['quantity']
            
            # Calculate ROI
            roi = (current_price - avg_entry) / avg_entry
            
            # Dynamic Profit Target
            # If volatility is high, we expect more "snap back" so we aim higher.
            # If we've been holding a long time (stale), lower target to free capital.
            target = self.target_profit_roi
            
            if stats['volatility'] > 0.015: 
                target = 0.025 # Aim for 2.5% in volatile markets
            
            # Decay target based on hold duration (ticks)
            pos['hold_ticks'] += 1
            if pos['hold_ticks'] > 50:
                target = max(self.min_profit_roi, target * 0.8) # Reduce expectations
            
            # EXECUTE SELL
            if roi >= target:
                proceeds = current_price * qty
                self.balance += proceeds
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f'ROI_{roi:.4f}']
                }

        # 3. Logic Priority 2: Manage Underwater Positions (DCA)
        # If we are holding a bag, and stats look good, buy more to lower avg entry.
        for symbol, pos in self.positions.items():
            if symbol not in market_stats: continue
            if pos['dca_count'] >= self.max_dca_count: continue # Cap exposure
            
            stats = market_stats[symbol]
            current_price = stats['price']
            z_score = stats['z_score']
            
            # DCA Conditions:
            # 1. Price is significantly below avg entry (Step-wise drops)
            # 2. Z-Score indicates it is currently oversold (not just dropping, but statistically cheap)
            
            # Determine depth requirement based on DCA count
            # DCA 1: needs -3% drop
            # DCA 2: needs -6% drop, etc.
            roi = (current_price - pos['avg_price']) / pos['avg_price']
            required_drop = -0.03 * (pos['dca_count'] + 1)
            
            # Determine Z requirement
            # Must be significantly oversold.
            required_z = self.base_z_entry - (0.5 * (pos['dca_count'] + 1))
            
            if roi < required_drop and z_score < required_z:
                # Martingale Sizing: Increase size to have impact
                investment = self.base_order_size * (1.5 ** (pos['dca_count'] + 1))
                
                if self.balance > investment:
                    buy_qty = investment / current_price
                    
                    # Update Weighted Average
                    total_cost = (pos['avg_price'] * pos['quantity']) + investment
                    total_qty = pos['quantity'] + buy_qty
                    
                    pos['avg_price'] = total_cost / total_qty
                    pos['quantity'] = total_qty
                    pos['dca_count'] += 1
                    self.balance -= investment
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': ['DCA_RESCUE', f'Z_{z_score:.2f}']
                    }

        # 4. Logic Priority 3: New Entries
        # Only if we have sufficient liquidity (keep buffer for DCA)
        liquidity_buffer = 500.0
        if self.balance > (self.base_order_size + liquidity_buffer):
            
            best_opportunity = None
            lowest_z = 0
            
            for symbol, stats in market_stats.items():
                if symbol in self.positions: continue
                
                z = stats['z_score']
                vol = stats['volatility']
                
                # Filter 1: Min Volatility (Don't buy flat lines)
                if vol < self.min_volatility: continue
                
                # Filter 2: Dynamic Z-Score Threshold
                # If vol is high (>1%), we demand a deeper discount (-3.0z) to catch the knife safely.
                # If vol is normal, we accept base entry (-2.1z).
                threshold = self.base_z_entry
                if vol > 0.01:
                    threshold = self.base_z_entry * 1.4 # Requires -2.94 roughly
                
                if z < threshold:
                    # Pick the most oversold asset
                    if best_opportunity is None or z < lowest_z:
                        best_opportunity = symbol
                        lowest_z = z
            
            if best_opportunity:
                stats = market_stats[best_opportunity]
                amount = self.base_order_size / stats['price']
                
                self.positions[best_opportunity] = {
                    'avg_price': stats['price'],
                    'quantity': amount,
                    'dca_count': 0,
                    'hold_ticks': 0
                }
                self.balance -= self.base_order_size
                
                return {
                    'side': 'BUY',
                    'symbol': best_opportunity,
                    'amount': amount,
                    'reason': ['ENTRY_MEAN_REV', f'Z_{lowest_z:.2f}']
                }

        return None