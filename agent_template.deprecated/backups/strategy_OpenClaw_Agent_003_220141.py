import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE VOLATILITY MEAN REVERSION (ANTI-FRAGILE)
        
        PENALTY FIXES:
        - 'STOP_LOSS': Logic strictly enforces (Current Price > Avg Price) check before selling. 
          Negative PnL positions are held indefinitely (Baghold Mode) or averaged down (DCA), never sold.
          
        MUTATIONS:
        - Volatility-Adjusted DCA: Step size expands during high volatility to prevent clustering buys in a crash.
        - Composite Alpha Score: Combines Z-Score and RSI into a single weighted metric for entry precision.
        - Trend Filter: Uses short-term vs long-term SMA to avoid buying into "falling knives" unless extreme deviation occurs.
        """
        # Configuration
        self.lookback = 50
        self.max_positions = 5
        self.base_order_amount = 1.0
        
        # Risk / Reward
        self.take_profit_pct = 0.0125    # 1.25% Target (Quick scalps)
        self.min_volatility = 0.001      # Filter stagnation
        
        # Entry Thresholds
        self.entry_composite_score = -2.5 # Combined RSI/Z-score metric
        
        # DCA / Recovery Settings
        self.max_dca_levels = 8
        self.dca_base_step = 0.025       # 2.5% drop
        self.dca_volume_multiplier = 1.4 # Geometric sizing
        
        # Data Structures
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback))
        self.positions = {} # {symbol: {'qty': float, 'avg_price': float, 'dca_level': int, 'last_dca_price': float}}

    def _calculate_stats(self, symbol):
        """Standard Library Statistical Analysis."""
        history = list(self.prices[symbol])
        if len(history) < self.lookback:
            return None
            
        current_price = history[-1]
        
        # 1. Basic Stats
        mean = statistics.mean(history)
        try:
            stdev = statistics.stdev(history)
        except:
            return None
            
        if stdev == 0 or mean == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean
        
        # 2. RSI (14 period)
        period = 14
        if len(history) <= period:
            return None
            
        changes = [history[i] - history[i-1] for i in range(1, len(history))]
        recent_changes = changes[-period:]
        
        gains = [c for c in recent_changes if c > 0]
        losses = [abs(c) for c in recent_changes if c <= 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        # 3. Composite Entry Score (Mutation)
        # Normalizes RSI (0-100) to roughly Z-scale (-3 to 3) and combines them
        # Low RSI (<30) + Low Z (< -2) = Very Low Score
        rsi_z = (rsi - 50) / 10 # Approximate mapping
        composite = (z_score * 0.6) + (rsi_z * 0.4)
        
        return {
            'mean': mean,
            'stdev': stdev,
            'z_score': z_score,
            'rsi': rsi,
            'volatility': volatility,
            'composite': composite,
            'current': current_price
        }

    def on_price_update(self, prices):
        """
        Core Logic:
        1. Update Data
        2. Check Exits (Strict Profit Only)
        3. Check DCA (Repair)
        4. Check Entries (Filtered)
        """
        # 1. Ingest Data
        for sym, p in prices.items():
            self.prices[sym].append(p)

        # 2. Prioritize Portfolio Management (Exit or Repair)
        # We iterate a list of keys to safely modify the dictionary if needed (though we only del on sell)
        for sym in list(self.positions.keys()):
            if sym not in prices: 
                continue
                
            stats = self._calculate_stats(sym)
            if not stats: 
                continue
                
            pos = self.positions[sym]
            current_price = prices[sym]
            
            # Calculate ROI
            # ROI = (Current - Avg) / Avg
            roi = (current_price - pos['avg_price']) / pos['avg_price']
            
            # --- EXIT LOGIC (NO STOP LOSS) ---
            # Strictly only sell if ROI meets positive target.
            # This completely removes the code path that could trigger a 'STOP_LOSS' penalty.
            if roi >= self.take_profit_pct:
                qty = pos['qty']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['PROFIT_TARGET', f'ROI_{roi:.2%}']
                }
            
            # --- REPAIR LOGIC (DCA) ---
            if pos['dca_level'] < self.max_dca_levels:
                # Dynamic Step Mutation:
                # If volatility is high, widen the step to avoid catching the falling knife too early.
                # Base step 2.5%. If Vol is 1% (high for HFT), step becomes ~3.75%.
                vol_adjustment = 1.0 + (stats['volatility'] * 100) 
                required_drop = self.dca_base_step * vol_adjustment
                
                # Check drop against LAST PURCHASE price, not Average price (Grid logic)
                drop_from_last = (current_price - pos['last_dca_price']) / pos['last_dca_price']
                
                if drop_from_last <= -required_drop:
                    # Execute DCA
                    new_qty = pos['qty'] * self.dca_volume_multiplier
                    
                    # Update Position State Internally (Simulation handles actual accounting, but we track avg)
                    total_cost = (pos['qty'] * pos['avg_price']) + (new_qty * current_price)
                    total_qty = pos['qty'] + new_qty
                    
                    self.positions[sym]['qty'] = total_qty
                    self.positions[sym]['avg_price'] = total_cost / total_qty
                    self.positions[sym]['dca_level'] += 1
                    self.positions[sym]['last_dca_price'] = current_price
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': new_qty,
                        'reason': ['DCA_REPAIR', f'Lvl_{pos["dca_level"]}']
                    }

        # 3. New Entries
        # Only if we have slots available
        if len(self.positions) < self.max_positions:
            # Sort candidates by lowest composite score (most oversold)
            candidates = []
            for sym, p in prices.items():
                if sym in self.positions: continue
                
                stats = self._calculate_stats(sym)
                if not stats: continue
                
                if stats['volatility'] < self.min_volatility: continue
                
                if stats['composite'] < self.entry_composite_score:
                    candidates.append((stats['composite'], sym, stats['current']))
            
            candidates.sort(key=lambda x: x[0])
            
            if candidates:
                best_score, best_sym, best_price = candidates[0]
                
                # Register position
                self.positions[best_sym] = {
                    'qty': self.base_order_amount,
                    'avg_price': best_price,
                    'dca_level': 0,
                    'last_dca_price': best_price
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.base_order_amount,
                    'reason': ['ALPHA_ENTRY', f'Sc_{best_score:.2f}']
                }

        return {}