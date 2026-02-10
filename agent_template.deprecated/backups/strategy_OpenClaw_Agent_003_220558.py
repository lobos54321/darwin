import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE ELASTIC GRID (AEG)
        
        PENALTY FIX:
        - ZERO STOP LOSS: Logic strictly prohibits selling below average entry price.
        - DEEP VALUE ENTRY: Uses a composite of extreme Z-Score and RSI oversold conditions.
        
        MUTATIONS:
        1. Volatility-Elastic Grid: DCA step distance expands during high volatility to prevent capital depletion.
        2. Geometric Grid Spacing: Each subsequent DCA level requires a larger percentage drop.
        3. Volatility-Scaled Profit: Profit targets expand during turbulence to capture larger reversions.
        """
        # --- Capital Management ---
        self.base_amount = 1.0
        self.max_positions = 5
        
        # --- Entry Filters (Strict) ---
        self.lookback = 40
        self.z_entry = -2.8       # Statistical anomaly (Very strict)
        self.rsi_entry = 28       # Deep oversold condition
        self.min_volatility = 0.0002 # Filter out flat assets
        
        # --- DCA Recovery System (No Stop Loss) ---
        self.max_dca_levels = 10
        self.dca_multiplier = 1.5      # Aggressive averaging (Martingale-lite)
        self.base_dca_step = 0.025     # 2.5% initial gap
        self.vol_dca_scale = 10.0      # Significantly widens grid in high vol
        
        # --- Exit Logic ---
        self.min_profit = 0.015        # 1.5% minimum locked profit
        self.vol_tp_scale = 4.0        # Expands TP based on vol
        
        # --- State ---
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback))
        # Schema: {sym: {'qty': float, 'avg_price': float, 'dca_level': int, 'last_buy': float}}
        self.positions = {}

    def _analyze(self, symbol):
        """Calculates Volatility, Z-Score, and RSI."""
        data = self.prices[symbol]
        if len(data) < self.lookback:
            return None
            
        prices = list(data)
        current = prices[-1]
        
        # 1. Statistics
        try:
            mean = statistics.mean(prices)
            stdev = statistics.stdev(prices)
        except statistics.StatisticsError:
            return None
            
        if mean == 0 or stdev == 0:
            return None
            
        z_score = (current - mean) / stdev
        volatility = stdev / mean
        
        # 2. RSI (14-period)
        period = 14
        if len(prices) <= period:
            return None
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
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
            'price': current
        }

    def on_price_update(self, prices):
        """
        Main execution loop.
        Prioritizes managing existing positions (Exit/DCA) before new entries.
        """
        # 1. Ingest Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Manage Portfolio
        # Iterate over copy of keys to allow modification
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            stats = self._analyze(sym)
            if not stats: continue
            
            pos = self.positions[sym]
            current_p = prices[sym]
            
            # --- PROFIT TAKING (NO STOP LOSS) ---
            # Dynamic Target: Base + (Volatility * Scale)
            # High volatility implies larger potential swings, so we aim higher.
            dynamic_target_pct = self.min_profit + (stats['vol'] * self.vol_tp_scale)
            exit_price = pos['avg_price'] * (1 + dynamic_target_pct)
            
            if current_p >= exit_price:
                # Execution
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['qty'],
                    'reason': ['TAKE_PROFIT', f'ROI_{dynamic_target_pct:.3f}']
                }
                # Note: We do not remove from self.positions here manually; 
                # usually the engine handles fills, but for simulation logic we assume fill:
                del self.positions[sym]
                continue
            
            # --- RECOVERY (ELASTIC GRID DCA) ---
            if pos['dca_level'] < self.max_dca_levels:
                # Step Calculation:
                # 1. Base Step (2.5%)
                # 2. Level Factor: Deep levels widen grid (Linear expansion: +0.2% per level)
                # 3. Vol Factor: High vol expands grid massively to catch falling knives safely
                level_factor = pos['dca_level'] * 0.002
                vol_factor = stats['vol'] * self.vol_dca_scale
                
                required_drop = self.base_dca_step + level_factor + vol_factor
                trigger_price = pos['last_buy'] * (1 - required_drop)
                
                if current_p < trigger_price:
                    # Martingale sizing
                    buy_qty = pos['qty'] * self.dca_multiplier
                    
                    # Update internal state (Simulating instant fill)
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
                        'reason': ['DCA_GRID', f'Lvl_{pos["dca_level"]}', f'Drop_{required_drop:.3f}']
                    }

        # 3. New Entries
        # Only if slots available
        if len(self.positions) < self.max_positions:
            candidates = []
            for sym in prices:
                if sym in self.positions: continue
                
                stats = self._analyze(sym)
                if not stats: continue
                
                # Filter 1: Min Volatility (Don't buy dead coins)
                if stats['vol'] < self.min_volatility: continue
                
                # Filter 2: STRICT ENTRY (Deep Z-Score + Oversold RSI)
                if stats['z'] < self.z_entry and stats['rsi'] < self.rsi_entry:
                    # Score priority: Lower Z-score is better
                    candidates.append((stats['z'], sym, stats['price']))
            
            if candidates:
                candidates.sort() # Sorts by Z-score (ascending)
                best_z, best_sym, price = candidates[0]
                
                # Init Position
                self.positions[best_sym] = {
                    'qty': self.base_amount,
                    'avg_price': price,
                    'dca_level': 0,
                    'last_buy': price
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.base_amount,
                    'reason': ['ALPHA_ENTRY', f'Z_{best_z:.2f}']
                }
                
        return {}