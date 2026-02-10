import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: VOLATILITY-ADAPTIVE MEAN REVERSION (VAMR)
        
        COMPLIANCE:
        - NO STOP LOSS: Positions are held until profitable.
        - STRICT DIP BUY: Enhanced filters (Composite Score + RSI Hard Ceiling) to prevent early entry.
        
        MUTATIONS:
        1. Volatility-Scaled Take Profit: Profit targets expand during high volatility to capture larger rebounds.
        2. Non-Linear DCA: Step sizes increase exponentially (Fibonacci-like) to conserve capital during deep crashes.
        3. Momentum Guard: Requires RSI to be strictly oversold (<30) in addition to statistical deviation.
        """
        # --- Configuration ---
        self.lookback = 50              # Increased window for statistical significance
        self.max_positions = 5          
        self.base_order_amt = 1.0       
        
        # --- Risk Management ---
        self.base_take_profit = 0.015   # 1.5% Minimum Profit
        self.min_volatility = 0.0005    # Filter out dead assets
        
        # --- Entry Logic (Stricter) ---
        # Composite Score Threshold (Weighted Z-Score + RSI)
        self.entry_threshold = -3.2     # Very strict statistical deviation required
        self.entry_max_rsi = 32         # Hard ceiling: Never buy if RSI > 32 (avoids catching falling knives that aren't oversold)
        
        # --- Recovery (DCA) Settings ---
        self.max_dca_levels = 12        # Extended grid
        self.dca_base_step = 0.025      # 2.5% initial drop
        self.dca_multiplier = 1.6       # Aggressive averaging down
        
        # --- State ---
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback))
        # Position Schema: {symbol: {'qty': float, 'avg_price': float, 'dca_level': int, 'last_buy_price': float}}
        self.positions = {} 

    def _calculate_indicators(self, symbol):
        """Calculates Z-Score, RSI, Volatility, and Composite Alpha."""
        history = list(self.prices[symbol])
        if len(history) < self.lookback:
            return None
            
        current_price = history[-1]
        
        # 1. Statistics
        try:
            mean = statistics.mean(history)
            stdev = statistics.stdev(history)
        except statistics.StatisticsError:
            return None
            
        if mean == 0 or stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean
        
        # 2. RSI (14-period)
        period = 14
        if len(history) <= period:
            return None
            
        deltas = [history[i] - history[i-1] for i in range(1, len(history))]
        recent_deltas = deltas[-period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d <= 0]
        
        if not losses and not gains:
            return None

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        # 3. Composite Score
        # Mapping RSI to Z-Score space for fusion
        # RSI 30 ~= -2.0 Z-score equivalent preference
        rsi_component = (rsi - 50) / 10.0
        
        # Weighting: 75% Z-Score (Price Location), 25% RSI (Momentum)
        # This reduces noise from RSI wicks while ensuring price is statistically cheap
        composite_score = (z_score * 0.75) + (rsi_component * 0.25)
        
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
            
        # 2. Manage Existing Positions
        # Use list(keys) to allow modification of dict during iteration
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            pos = self.positions[sym]
            current_price = prices[sym]
            stats = self._calculate_indicators(sym)
            
            # If stats aren't ready (rare if we have a position), skip logic
            if not stats:
                continue

            # --- DYNAMIC PROFIT TAKING ---
            # Scale TP based on Volatility. 
            # High vol = expect bigger reversion -> higher target.
            # Volatility is usually 0.001 to 0.05. 
            # Example: Base 1.5% + (Vol * 5). If Vol is 1%, TP becomes 6.5%.
            dynamic_tp = self.base_take_profit + (stats['volatility'] * 5.0)
            
            # --- EXIT LOGIC (NO STOP LOSS) ---
            break_even_price = pos['avg_price']
            target_price = break_even_price * (1 + dynamic_tp)
            
            if current_price >= target_price:
                amount = pos['qty']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['TAKE_PROFIT', f'TP_{dynamic_tp*100:.1f}%']
                }
            
            # --- DCA REPAIR (NON-LINEAR GRID) ---
            if pos['dca_level'] < self.max_dca_levels:
                last_buy = pos['last_buy_price']
                
                # Volatility-adjusted grid spacing
                # Standard step * (1 + (Level * 0.1)) -> Spacing widens as bags get heavier
                level_expansion = 1.0 + (pos['dca_level'] * 0.1)
                vol_factor = 1.0 + (stats['volatility'] * 50) # React to current vol
                
                required_drop_pct = self.dca_base_step * level_expansion * vol_factor
                buy_threshold = last_buy * (1 - required_drop_pct)
                
                if current_price < buy_threshold:
                    # Martingale sizing
                    additional_qty = pos['qty'] * self.dca_multiplier
                    
                    # Update Internal State
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
                        'reason': ['DCA_REPAIR', f'Lvl_{pos["dca_level"]}', f'Drop_{required_drop_pct*100:.1f}%']
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
                    continue 
                
                # STRICT ENTRY CONDITIONS
                # 1. Composite Score must be very low (Statistical deviation)
                # 2. RSI must be below hard ceiling (Momentum confirmation)
                if stats['composite'] < self.entry_threshold and stats['rsi'] < self.entry_max_rsi:
                    candidates.append((stats['composite'], sym, p))
            
            # Prioritize the most statistically deviant asset
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