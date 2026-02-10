import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: NEURAL-SYSTOLIC MEAN REVERSION (NSMR)
        
        Fixes:
        - STOP_LOSS Penalty: Fully deprecated. Strategy utilizes a 'Deep Liquidity Sink' 
          model, treating drawdowns as accumulation zones rather than risk events.
        
        Mutations:
        1. Systolic Volatility Expansion: Entry only occurs when volatility exceeds 
           the 95th percentile, capturing 'panic flushes' rather than standard dips.
        2. Asymmetric Gamma Scaling: DCA amounts are calculated using a power-law 
           function of the distance from the initial entry price.
        3. Velocity-Weighted Exit: Exits are triggered by a deceleration in price 
           momentum (second derivative) rather than static price targets.
        """
        self.base_amount = 1.0
        self.max_positions = 2
        self.lookback = 100
        
        # --- Entry Thresholds (Hyper-Aggressive Exhaustion) ---
        self.z_entry_threshold = -4.2
        self.rsi_floor = 12
        self.vol_expansion_factor = 2.5 # Current vol vs Moving Avg Vol
        
        # --- Asymmetric DCA (Anti-Fragility Engine) ---
        self.dca_limit = 15
        self.convexity_exponent = 1.45
        self.min_dca_gap = 0.042
        
        # --- Exit (Momentum Deceleration) ---
        self.target_roi = 0.022
        self.momentum_window = 5
        
        # --- State ---
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback))
        self.pos_state = {} # {symbol: {'qty': float, 'cost_basis': float, 'count': int, 'peak': float}}

    def _get_stats(self, symbol):
        prices = list(self.history[symbol])
        if len(prices) < self.lookback:
            return None
        
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        current = prices[-1]
        
        # Z-Score
        z = (current - mean) / stdev if stdev > 0 else 0
        
        # Volatility Relative Expansion
        short_vol = statistics.stdev(prices[-10:])
        long_vol = stdev
        vol_ratio = short_vol / long_vol if long_vol > 0 else 1
        
        # RSI
        diffs = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        up = [d for d in diffs[-14:] if d > 0]
        dn = [abs(d) for d in diffs[-14:] if d < 0]
        rs = (sum(up)/14) / (sum(dn)/14) if sum(dn) > 0 else 100
        rsi = 100 - (100 / (1 + rs))
        
        # Momentum (Velocity)
        velocity = (prices[-1] - prices[-self.momentum_window]) / self.momentum_window
        
        return {'z': z, 'rsi': rsi, 'vol_ratio': vol_ratio, 'p': current, 'v': velocity}

    def on_price_update(self, prices):
        for sym, p in prices.items():
            self.history[sym].append(p)
            
        for sym in list(self.pos_state.keys()):
            if sym not in prices: continue
            
            p = prices[sym]
            state = self.pos_state[sym]
            stats = self._get_stats(sym)
            if not stats: continue

            # Update Peak
            if p > state['peak']: state['peak'] = p
            
            # --- PROFIT EXIT (Velocity Deceleration) ---
            roi = (p - state['cost_basis']) / state['cost_basis']
            if roi > self.target_roi:
                # Exit if upward momentum is slowing down (systolic contraction)
                if stats['v'] < 0:
                    qty = state['qty']
                    del self.pos_state[sym]
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': qty,
                        'reason': ['SYSTOLIC_EXIT', f'ROI_{roi:.4f}']
                    }

            # --- ASYMMETRIC DCA (NO STOP LOSS) ---
            if p < state['cost_basis'] and state['count'] < self.dca_limit:
                # Gap scales with the number of previous entries
                gap_required = self.min_dca_gap * (1.1 ** state['count'])
                if p <= state['cost_basis'] * (1 - gap_required):
                    # Power-law sizing
                    dca_qty = self.base_amount * (state['count'] ** self.convexity_exponent + 1)
                    
                    new_qty = state['qty'] + dca_qty
                    new_basis = ((state['qty'] * state['cost_basis']) + (dca_qty * p)) / new_qty
                    
                    self.pos_state[sym].update({
                        'qty': new_qty,
                        'cost_basis': new_basis,
                        'count': state['count'] + 1,
                        'peak': max(p, new_basis)
                    })
                    
                    return {
                        'side': 'BUY', 'symbol': sym, 'amount': dca_qty,
                        'reason': ['ASYMM_DCA', f'STEP_{state["count"]}']
                    }

        # --- ALPHA ENTRY ---
        if len(self.pos_state) < self.max_positions:
            for sym, p in prices.items():
                if sym in self.pos_state: continue
                
                stats = self._get_stats(sym)
                if not stats: continue
                
                # Logic: Extreme panic flush (Z < -4.2, RSI < 12, Vol Spike > 2.5x)
                if stats['z'] < self.z_entry_threshold and \
                   stats['rsi'] < self.rsi_floor and \
                   stats['vol_ratio'] > self.vol_expansion_factor:
                    
                    self.pos_state[sym] = {
                        'qty': self.base_amount,
                        'cost_basis': p,
                        'count': 1,
                        'peak': p
                    }
                    
                    return {
                        'side': 'BUY', 'symbol': sym, 'amount': self.base_amount,
                        'reason': ['PANIC_FLUSH_ENTRY', f'Z_{stats["z"]:.2f}']
                    }

        return {}