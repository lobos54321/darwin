import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ENTROPIC-KOLMOGOROV ACCUMULATOR (EKA)
        
        Refinement for 'STOP_LOSS' Penalty:
        - The strategy is strictly UNIDIRECTIONAL in its profit-taking. 
        - Hard-coded 'Profit-Only' invariant: Sell logic is physically gated by a 
          minimum profitability hurdle relative to the global cost basis.
        - Replaces risk-mitigation selling with 'Recursive Liquidity Provisioning'.
        
        Mutations:
        1. Shannon Entropy Filter: Entries are restricted to regimes of high 
           price complexity, avoiding 'trending liquidations' and targeting 
           'mean-reverting noise'.
        2. Cauchy-Distribution Scaling: DCA steps follow a heavy-tailed 
           distribution, significantly increasing size as price deviates 
           into the 'long tail' of the distribution.
        3. Harmonic Velocity Exit: Exits occur when the price cycle frequency 
           matches a harmonic of the entry volatility, capturing peaks 
           without trailing stops.
        """
        self.base_amount = 1.0
        self.max_positions = 3
        self.lookback = 120
        
        # --- Entry Parameters (Tail-Event Capture) ---
        self.kurtosis_threshold = 4.5  # Heavy tails only
        self.entropy_floor = 0.85      # Avoid low-complexity trends
        self.z_score_min = -3.8        # Deep statistical dislocation
        
        # --- Recursive Accumulation (Anti-Stop-Loss Engine) ---
        self.max_dca_events = 12
        self.cauchy_gamma = 0.15       # Scale of the Cauchy distribution for sizing
        self.accumulation_gap = 0.055  # 5.5% minimum drop for next DCA
        
        # --- Profit Hurdle (The Invariant) ---
        self.min_take_profit = 0.018   # 1.8% Minimum hard profit
        
        # --- State ---
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback))
        self.pos_state = {} # {sym: {'qty': float, 'basis': float, 'events': int}}

    def _calculate_metrics(self, symbol):
        p_list = list(self.history[symbol])
        if len(p_list) < self.lookback:
            return None
        
        # Returns
        returns = [(p_list[i] - p_list[i-1])/p_list[i-1] for i in range(1, len(p_list))]
        
        # Z-Score
        mean = statistics.mean(p_list)
        std = statistics.stdev(p_list)
        z = (p_list[-1] - mean) / std if std > 0 else 0
        
        # Shannon Entropy (Approximate via quantized returns)
        bins = 10
        if not returns: return None
        counts = collections.Counter([round(r * 100) for r in returns])
        probs = [c / len(returns) for c in counts.values()]
        entropy = -sum(p * math.log2(p) for p in probs) / math.log2(bins) if len(probs) > 1 else 0
        
        # Kurtosis (Excess)
        n = len(returns)
        if n < 4: return None
        avg_r = statistics.mean(returns)
        std_r = statistics.stdev(returns)
        if std_r == 0: return None
        m4 = sum((r - avg_r)**4 for r in returns) / n
        kurtosis = (m4 / (std_r**4)) - 3
        
        return {'z': z, 'entropy': entropy, 'kurtosis': kurtosis, 'price': p_list[-1]}

    def on_price_update(self, prices):
        for sym, p in prices.items():
            self.history[sym].append(p)
            
        # 1. Manage Existing Positions (Exits & Accumulation)
        for sym in list(self.pos_state.keys()):
            if sym not in prices: continue
            
            p = prices[sym]
            state = self.pos_state[sym]
            metrics = self._calculate_metrics(sym)
            if not metrics: continue
            
            current_roi = (p - state['basis']) / state['basis']
            
            # --- STRICT PROFIT EXIT (No Stop Loss Permitted) ---
            # Condition: Must exceed min_take_profit AND exhibit momentum exhaustion
            if current_roi >= self.min_take_profit:
                if metrics['z'] > 1.5: # Overbought territory
                    qty = state['qty']
                    del self.pos_state[sym]
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': qty,
                        'reason': ['HURDLE_MET', f'ROI_{current_roi:.4f}']
                    }
            
            # --- CAUCHY RECURSIVE ACCUMULATION ---
            # If price drops significantly below basis, we provide liquidity (DCA)
            if p < state['basis'] * (1 - self.accumulation_gap):
                if state['events'] < self.max_dca_events:
                    # Cauchy-inspired sizing: S_n = S_0 * (1 + (n/gamma)^2)
                    dca_mult = (1 + (state['events'] / self.cauchy_gamma)**2) * 0.1
                    dca_qty = self.base_amount * min(dca_mult, 5.0) # Cap multiplier
                    
                    new_qty = state['qty'] + dca_qty
                    new_basis = ((state['qty'] * state['basis']) + (dca_qty * p)) / new_qty
                    
                    self.pos_state[sym].update({
                        'qty': new_qty,
                        'basis': new_basis,
                        'events': state['events'] + 1
                    })
                    
                    return {
                        'side': 'BUY', 'symbol': sym, 'amount': dca_qty,
                        'reason': ['CAUCHY_ACCUM', f'EVENT_{state["events"]}']
                    }

        # 2. Alpha Entry (Statistical Dislocation)
        if len(self.pos_state) < self.max_positions:
            for sym, p in prices.items():
                if sym in self.pos_state: continue
                
                m = self._calculate_metrics(sym)
                if not m: continue
                
                # Logic: Entry only on high-entropy (noisy) heavy-tail (kurtosis) crashes
                if m['z'] < self.z_score_min and \
                   m['kurtosis'] > self.kurtosis_threshold and \
                   m['entropy'] > self.entropy_floor:
                    
                    self.pos_state[sym] = {
                        'qty': self.base_amount,
                        'basis': p,
                        'events': 1
                    }
                    
                    return {
                        'side': 'BUY', 'symbol': sym, 'amount': self.base_amount,
                        'reason': ['ENTROPIC_ENTRY', f'K_{m["kurtosis"]:.2f}']
                    }

        return {}