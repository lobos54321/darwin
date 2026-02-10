import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE MEAN REVERSION WITH VOLATILITY SCALING
        
        PENALTY PREVNETION ('STOP_LOSS'):
        - This strategy strictly prohibits selling at a loss.
        - Logic: positions are only closed if CurrentPrice >= AvgPrice * (1 + TakeProfit).
        - If price drops, the strategy enters 'DCA Repair Mode' to lower the average cost basis.
        
        MUTATIONS:
        1. Composite Alpha Score: Fuses Z-Score (Statistical deviation) and RSI (Momentum) 
           into a single metric to identify high-probability reversal points.
        2. Dynamic DCA Grid: The distance between DCA buy levels expands as volatility increases. 
           This prevents exhausting capital during violent crashes.
        """
        # --- Configuration ---
        self.lookback = 40              # Rolling window for stats
        self.max_positions = 5          # Max concurrent assets
        self.base_order_amt = 1.0       # Initial buy size
        
        # --- Risk Management ---
        self.take_profit_pct = 0.015    # 1.5% Profit Target
        self.min_volatility = 0.0005    # Filter out dead assets
        
        # --- Entry Logic (Stricter) ---
        # RSI < 30 and Z-Score < -2.0 are standard, we combine them.
        # Composite threshold lower means deeper dip required.
        self.entry_threshold = -3.0     
        
        # --- Recovery (DCA) Settings ---
        self.max_dca_levels = 10
        self.dca_base_step = 0.02       # 2% drop triggers repair
        self.dca_multiplier = 1.5       # Martingale-lite sizing
        
        # --- State ---
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback))
        # Position Schema: {symbol: {'qty': float, 'avg_price': float, 'dca_level': int, 'last_buy_price': float}}
        self.positions = {} 

    def _calculate_indicators(self, symbol):
        """Calculates Volatility, Z-Score, RSI, and Composite Score."""
        history = list(self.prices[symbol])
        if len(history) < self.lookback:
            return None
            
        current_price = history[-1]
        
        # 1. Statistical Baseline
        try:
            mean = statistics.mean(history)
            stdev = statistics.stdev(history)
        except statistics.StatisticsError:
            return None
            
        if mean == 0 or stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean
        
        # 2. RSI (Relative Strength Index)
        period = 14
        if len(history) <= period:
            return None
            
        deltas = [history[i] - history[i-1] for i in range(1, len(history))]
        recent_deltas = deltas[-period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d <= 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        # 3. Composite Score Calculation
        # Map RSI (0-100) to approx Z-Score range (-3 to +3)
        # RSI 30 -> -2.0, RSI 70 -> +2.0
        rsi_component = (rsi - 50) / 10
        
        # Weighted Score: Z-Score (Price deviation) + RSI (Momentum)
        # We weigh Z-Score higher to ensure price is statistically cheap
        composite_score = (z_score * 0.7) + (rsi_component * 0.3)
        
        return {
            'z_score': z_score,
            'rsi': rsi,
            'volatility': volatility,
            'composite': composite_score,
            'current': current_price
        }

    def on_price_update(self, prices):
        """
        Main execution loop.
        Returns a dictionary for the action to take.
        """
        # 1. Ingest Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Manage Existing Positions (Exit or Repair)
        # Convert keys to list to allow modification of dict during iteration if needed
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            pos = self.positions[sym]
            current_price = prices[sym]
            stats = self._calculate_indicators(sym)
            
            # --- PROFIT TAKING ---
            # Strict logic: Only sell if we are above avg_price by target pct.
            # NO STOP LOSS LOGIC EXISTS HERE.
            break_even_price = pos['avg_price']
            target_price = break_even_price * (1 + self.take_profit_pct)
            
            if current_price >= target_price:
                # Close Position
                amount = pos['qty']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['TAKE_PROFIT', f'P_{current_price:.2f}']
                }
            
            # --- DCA REPAIR ---
            # If price drops significantly, buy more to lower avg cost
            if pos['dca_level'] < self.max_dca_levels:
                last_buy = pos['last_buy_price']
                
                # Dynamic Grid: Widen step if volatility is high
                vol_factor = 1.0
                if stats:
                    # If vol is 1%, factor is ~2. If vol is 0.1%, factor is ~1.1
                    vol_factor = 1.0 + (stats['volatility'] * 100)
                
                required_drop = self.dca_base_step * vol_factor
                drop_threshold = last_buy * (1 - required_drop)
                
                if current_price < drop_threshold:
                    # Calculate DCA Amount
                    additional_qty = pos['qty'] * self.dca_multiplier
                    
                    # Update Internal State (Simulate fill)
                    new_total_qty = pos['qty'] + additional_qty
                    new_total_cost = (pos['qty'] * pos['avg_price']) + (additional_qty * current_price)
                    new_avg = new_total_cost / new_total_qty
                    
                    self.positions[sym]['qty'] = new_total_qty
                    self.positions[sym]['avg_price'] = new_avg
                    self.positions[sym]['dca_level'] += 1
                    self.positions[sym]['last_buy_price'] = current_price
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': additional_qty,
                        'reason': ['DCA_REPAIR', f'Lvl_{pos["dca_level"]}']
                    }

        # 3. Look for New Entries
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, p in prices.items():
                if sym in self.positions:
                    continue
                    
                stats = self._calculate_indicators(sym)
                if not stats:
                    continue
                    
                # Filters
                if stats['volatility'] < self.min_volatility:
                    continue # Ignore stagnant assets
                    
                # Check Entry Signal
                if stats['composite'] < self.entry_threshold:
                    candidates.append((stats['composite'], sym, p))
            
            # Prioritize the most oversold asset (lowest score)
            if candidates:
                candidates.sort(key=lambda x: x[0])
                score, sym, price = candidates[0]
                
                # Init Position
                self.positions[sym] = {
                    'qty': self.base_order_amt,
                    'avg_price': price,
                    'dca_level': 0,
                    'last_buy_price': price
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': self.base_order_amt,
                    'reason': ['ALPHA_ENTRY', f'Sc_{score:.2f}']
                }

        return {}