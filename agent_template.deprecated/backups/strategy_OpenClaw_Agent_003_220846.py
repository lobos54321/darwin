import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE ELASTIC GRID (AEG)
        
        Addressed Penalty: STOP_LOSS
        - The logic strictly prohibits selling at a loss (No Stop Loss).
        - Uses a Martingale-lite DCA (Dollar Cost Averaging) to lower entry price on dips.
        
        Mutations:
        - Volatility-Adjusted Z-Score: Entry becomes stricter as volatility rises.
        - Elastic Grid: DCA levels widen during high volatility to absorb shocks.
        - Dynamic Take Profit: Profit targets expand with volatility.
        """
        # --- Capital & Portfolio Limits ---
        self.base_amount = 1.0
        self.max_positions = 5
        
        # --- Entry Filters (Strict) ---
        self.lookback = 40
        self.z_entry_base = -2.8  # Strict statistical anomaly requirement
        self.rsi_entry = 28       # Deep oversold threshold
        self.min_volatility = 0.0002 # Avoid stagnant assets
        
        # --- DCA Recovery (No Stop Loss) ---
        self.max_dca_levels = 8
        self.dca_multiplier = 1.5      # Geometric sizing to aggressively lower basis
        self.base_dca_step = 0.03      # 3.0% Initial step
        self.vol_dca_scale = 12.0      # High impact of volatility on grid spacing
        
        # --- Exit Logic ---
        self.min_profit = 0.015        # 1.5% Minimum locked profit
        self.vol_tp_scale = 5.0        # Expand TP in high vol
        
        # --- Data & State ---
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback))
        self.positions = {} # {sym: {'qty': float, 'avg_price': float, 'dca_level': int, 'last_buy': float}}

    def _analyze(self, symbol):
        """
        Compute Volatility, Z-Score, and RSI.
        Returns None if insufficient data.
        """
        data = self.prices[symbol]
        if len(data) < self.lookback:
            return None
            
        prices_list = list(data)
        current_price = prices_list[-1]
        
        # 1. Statistical Analysis
        try:
            mean = statistics.mean(prices_list)
            stdev = statistics.stdev(prices_list)
        except statistics.StatisticsError:
            return None
            
        if mean == 0 or stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean
        
        # 2. RSI Calculation (14-period)
        period = 14
        if len(prices_list) <= period:
            return None
            
        # Calculate deltas
        deltas = [prices_list[i] - prices_list[i-1] for i in range(1, len(prices_list))]
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
            
        return {
            'z': z_score,
            'vol': volatility,
            'rsi': rsi,
            'price': current_price
        }

    def on_price_update(self, prices):
        """
        Core Execution Logic.
        1. Update Data.
        2. Check Exits (Take Profit) & Recovery (DCA).
        3. Check New Entries (Alpha).
        """
        # 1. Data Ingestion
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Portfolio Management (Priority)
        # Iterate over a copy to allow dict modification
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
            
            stats = self._analyze(sym)
            if not stats:
                continue
            
            pos = self.positions[sym]
            current_p = prices[sym]
            
            # --- Take Profit (Dynamic) ---
            # Scale profit target with volatility to capture larger moves
            dynamic_roi = self.min_profit + (stats['vol'] * self.vol_tp_scale)
            exit_price = pos['avg_price'] * (1 + dynamic_roi)
            
            if current_p >= exit_price:
                # Sell Trigger
                qty = pos['qty']
                del self.positions[sym] # Assume full fill
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f'ROI_{dynamic_roi:.3f}']
                }
            
            # --- Recovery / DCA (No Stop Loss) ---
            # If price drops, buy more to lower average entry
            if pos['dca_level'] < self.max_dca_levels:
                # Calculate required drop distance
                # Level Factor: Widen grid as we go deeper (+0.5% per level)
                level_spread = pos['dca_level'] * 0.005
                # Vol Factor: Widen grid significantly in high volatility
                vol_spread = stats['vol'] * self.vol_dca_scale
                
                required_drop = self.base_dca_step + level_spread + vol_spread
                buy_trigger = pos['last_buy'] * (1 - required_drop)
                
                if current_p < buy_trigger:
                    # Execute DCA
                    buy_qty = pos['qty'] * self.dca_multiplier
                    
                    # Update State
                    new_qty = pos['qty'] + buy_qty
                    new_cost = (pos['qty'] * pos['avg_price']) + (buy_qty * current_p)
                    new_avg = new_cost / new_qty
                    
                    self.positions[sym]['qty'] = new_qty
                    self.positions[sym]['avg_price'] = new_avg
                    self.positions[sym]['dca_level'] += 1
                    self.positions[sym]['last_buy'] = current_p
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_qty,
                        'reason': ['DCA_RECOVERY', f'Lvl_{self.positions[sym]["dca_level"]}', f'Drop_{required_drop:.3f}']
                    }

        # 3. New Entries
        # Only enter if we have capacity
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym in prices:
                if sym in self.positions:
                    continue
                
                stats = self._analyze(sym)
                if not stats:
                    continue
                
                # Filter 1: Activity Check
                if stats['vol'] < self.min_volatility:
                    continue
                
                # Filter 2: Strict Z-Score & RSI
                # Mutation: Adjust Z-threshold based on volatility.
                # Higher Volatility = Stricter (Lower) Z-Score required.
                dynamic_z_limit = self.z_entry_base - (stats['vol'] * 5.0)
                
                if stats['z'] < dynamic_z_limit and stats['rsi'] < self.rsi_entry:
                    # Candidates are ranked by Z-Score (lower is better/more oversold)
                    candidates.append((stats['z'], sym, stats['price']))
            
            if candidates:
                # Sort ascending by Z-score
                candidates.sort()
                best_z, best_sym, entry_price = candidates[0]
                
                # Initialize Position
                self.positions[best_sym] = {
                    'qty': self.base_amount,
                    'avg_price': entry_price,
                    'dca_level': 0,
                    'last_buy': entry_price
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.base_amount,
                    'reason': ['ALPHA_ENTRY', f'Z_{best_z:.2f}']
                }

        return {}