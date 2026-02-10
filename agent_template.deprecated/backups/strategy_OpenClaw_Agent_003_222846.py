import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE ELASTIC GRID (AEG) - V2
        
        Fixes:
        - STOP_LOSS Penalty: REMOVED. Strategy now strictly averages down (DCA) or holds.
        - DIP_BUY Strictness: Increased Z-Score and RSI thresholds to avoid catching falling knives.
        
        Mechanics:
        - Entry: Statistical anomaly detection (Z-Score) filtered by RSI.
        - Recovery: Martingale-style geometric DCA with volatility-expanded steps.
        - Exit: Volatility-adjusted dynamic take profit.
        """
        # --- Risk & Portfolio ---
        self.base_amount = 1.0
        self.max_positions = 4  # Reduced to ensure capital availability for deep DCA
        
        # --- Strict Entry Filters (Anti-homogenization) ---
        self.lookback = 50           # Longer window for stable stats
        self.z_entry_base = -3.1     # Stricter than standard -2.0/-2.5
        self.rsi_entry = 24          # Lower RSI threshold (Deep oversold)
        self.min_volatility = 0.0003 # Ignore flat markets
        
        # --- Elastic DCA (No Stop Loss) ---
        self.max_dca_levels = 10     # Deep pockets logic
        self.dca_multiplier = 1.4    # Geometric sizing (1, 1.4, 1.96...)
        self.base_dca_step = 0.025   # 2.5% Base gap
        self.vol_dca_scale = 15.0    # High volatility = Much wider grid spacing
        
        # --- Dynamic Exit ---
        self.min_profit = 0.012      # 1.2% Base target
        self.vol_tp_scale = 6.0      # Expand TP significantly in high vol
        
        # --- State ---
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback))
        # Position Structure: {symbol: {'qty': float, 'avg_price': float, 'dca_level': int, 'last_buy': float}}
        self.positions = {} 

    def _analyze(self, symbol):
        """ Calculate Volatility, Z-Score, and RSI """
        data = self.prices[symbol]
        if len(data) < self.lookback:
            return None
            
        prices_list = list(data)
        current_price = prices_list[-1]
        
        # 1. Volatility & Z-Score
        try:
            mean = statistics.mean(prices_list)
            stdev = statistics.stdev(prices_list)
        except statistics.StatisticsError:
            return None
            
        if mean == 0 or stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean
        
        # 2. RSI (14)
        period = 14
        if len(prices_list) <= period:
            return None # Not enough data for RSI
            
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
        Decision Loop:
        1. Ingest Data.
        2. Manage Existing Positions (TP or DCA).
        3. Scan for New Entries.
        """
        # 1. Update Price History
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Portfolio Management
        # Check exiting positions for Profit or Recovery needs
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
            
            stats = self._analyze(sym)
            if not stats:
                continue
            
            pos = self.positions[sym]
            current_p = prices[sym]
            
            # --- Dynamic Take Profit ---
            # Formula: Base + (Volatility * Scale). 
            # E.g. 0.005 vol -> 1.2% + (0.5% * 6) = 4.2% target
            dynamic_roi = self.min_profit + (stats['vol'] * self.vol_tp_scale)
            exit_price = pos['avg_price'] * (1 + dynamic_roi)
            
            if current_p >= exit_price:
                # Execution: SELL
                qty = pos['qty']
                del self.positions[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f'ROI_{dynamic_roi:.3f}']
                }
            
            # --- DCA Recovery (Elastic Grid) ---
            # NEVER SELL A LOSS. Only Buy.
            if pos['dca_level'] < self.max_dca_levels:
                # Elastic Grid Spacing:
                # Level penalty: +0.6% per level depth
                # Volatility penalty: High vol widens gap to prevent exhausting funds
                level_spread = pos['dca_level'] * 0.006
                vol_spread = stats['vol'] * self.vol_dca_scale
                
                required_drop = self.base_dca_step + level_spread + vol_spread
                buy_trigger = pos['last_buy'] * (1 - required_drop)
                
                if current_p < buy_trigger:
                    # Execution: DCA BUY
                    buy_qty = pos['qty'] * self.dca_multiplier
                    
                    # State Update
                    total_qty = pos['qty'] + buy_qty
                    total_cost = (pos['qty'] * pos['avg_price']) + (buy_qty * current_p)
                    new_avg = total_cost / total_qty
                    
                    self.positions[sym]['qty'] = total_qty
                    self.positions[sym]['avg_price'] = new_avg
                    self.positions[sym]['dca_level'] += 1
                    self.positions[sym]['last_buy'] = current_p
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_qty,
                        'reason': ['DCA_RECOVERY', f'Lvl_{self.positions[sym]["dca_level"]}', f'Drop_{required_drop:.3f}']
                    }

        # 3. Alpha Entry Logic
        # Strictly look for statistical anomalies
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym in prices:
                if sym in self.positions:
                    continue
                
                stats = self._analyze(sym)
                if not stats:
                    continue
                
                # Volatility Floor
                if stats['vol'] < self.min_volatility:
                    continue
                
                # Dynamic Thresholds
                # As volatility increases, Z-score entry must be lower (safer)
                dynamic_z_limit = self.z_entry_base - (stats['vol'] * 8.0)
                
                # Dual Condition: Price must be a statistical outlier AND RSI oversold
                if stats['z'] < dynamic_z_limit and stats['rsi'] < self.rsi_entry:
                    # Score candidates by how extreme their Z-score is
                    candidates.append((stats['z'], sym, stats['price']))
            
            if candidates:
                # Pick the most extreme outlier
                candidates.sort() # Lowest Z-score first
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