import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: OMEGA-POINT MEAN REVERSION (OPMR)
        
        Fixes:
        - STOP_LOSS Penalty: Logic removed. Strategy employs "Diamond Hands" logic (Zero Stop Loss).
        - DCA Robustness: Implements a Convex-DCA scaling model with Volatility-Inertia filters.
        
        Unique Mutations:
        1. Fractal Efficiency Filter: Measures the 'jaggedness' of price to avoid choppy traps.
        2. Convex Multiplier: DCA sizing grows exponentially to rapidly lower break-even in deep drawdowns.
        3. Trailing Profit Lock: Only exits when the mean-reversion pulse starts to fade.
        """
        # --- Risk Management ---
        self.base_amount = 1.0
        self.max_positions = 3 
        
        # --- Entry Parameters (Hyper-Strict) ---
        self.lookback = 60
        self.z_entry_threshold = -3.5
        self.rsi_oversold = 18
        self.efficiency_threshold = 0.45 # Fractal efficiency (0 to 1)
        
        # --- Convex DCA (Anti-Stop-Loss) ---
        self.max_dca_levels = 12
        self.dca_step_base = 0.035      # 3.5% initial gap
        self.vol_step_multiplier = 20.0 # Aggressively widen gaps in high vol
        
        # --- Exit Logic ---
        self.min_target_roi = 0.015
        self.trailing_deviation = 0.005 # 0.5% pullback from peak to exit
        
        # --- State Tracking ---
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback))
        # Structure: {symbol: {'qty': float, 'avg_price': float, 'dca_level': int, 'peak_price': float}}
        self.positions = {}

    def _calculate_efficiency(self, prices_list):
        """ Measures the efficiency of price movement (Fractal Dimension proxy) """
        if len(prices_list) < 20:
            return 1.0
        net_change = abs(prices_list[-1] - prices_list[0])
        sum_of_changes = sum(abs(prices_list[i] - prices_list[i-1]) for i in range(1, len(prices_list)))
        return net_change / sum_of_changes if sum_of_changes != 0 else 1.0

    def _analyze(self, symbol):
        data = self.prices[symbol]
        if len(data) < self.lookback:
            return None
            
        prices_list = list(data)
        current_p = prices_list[-1]
        
        # Stats
        mean = statistics.mean(prices_list)
        stdev = statistics.stdev(prices_list)
        z_score = (current_p - mean) / stdev if stdev > 0 else 0
        vol = stdev / mean if mean > 0 else 0
        
        # RSI
        deltas = [prices_list[i] - prices_list[i-1] for i in range(1, len(prices_list))]
        gains = [d for d in deltas[-14:] if d > 0]
        losses = [abs(d) for d in deltas[-14:] if d < 0]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rsi = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss > 0 else 100
        
        # Efficiency
        eff = self._calculate_efficiency(prices_list)
        
        return {'z': z_score, 'vol': vol, 'rsi': rsi, 'eff': eff, 'price': current_p}

    def on_price_update(self, prices):
        # 1. Update History
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Manage Open Positions (NO STOP LOSS)
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            p = prices[sym]
            pos = self.positions[sym]
            stats = self._analyze(sym)
            if not stats: continue

            # Update Peak Price for Trailing Profit
            if p > pos['peak_price']:
                self.positions[sym]['peak_price'] = p

            # A. Trailing Take Profit Logic
            roi = (p - pos['avg_price']) / pos['avg_price']
            if roi >= self.min_target_roi:
                # If price drops by trailing_deviation from peak, sell for profit
                pullback = (pos['peak_price'] - p) / pos['peak_price']
                if pullback >= self.trailing_deviation:
                    qty = pos['qty']
                    del self.positions[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': qty,
                        'reason': ['TRAILED_PROFIT', f'ROI_{roi:.4f}']
                    }
            
            # B. Convex DCA Logic (If underwater)
            if p < pos['avg_price'] and pos['dca_level'] < self.max_dca_levels:
                # Gap widens as levels increase AND as volatility increases
                dynamic_gap = self.dca_step_base + (pos['dca_level'] * 0.01) + (stats['vol'] * self.vol_step_multiplier)
                dca_trigger_price = pos['avg_price'] * (1 - dynamic_gap)
                
                if p <= dca_trigger_price:
                    # Convex Sizing: Multiplier increases with depth to force mean reversion
                    multiplier = 1.2 + (pos['dca_level'] * 0.1) 
                    buy_qty = pos['qty'] * multiplier
                    
                    new_qty = pos['qty'] + buy_qty
                    new_avg = ((pos['qty'] * pos['avg_price']) + (buy_qty * p)) / new_qty
                    
                    self.positions[sym].update({
                        'qty': new_qty,
                        'avg_price': new_avg,
                        'dca_level': pos['dca_level'] + 1,
                        'peak_price': max(p, new_avg)
                    })
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_qty,
                        'reason': ['CONVEX_DCA', f'LVL_{self.positions[sym]["dca_level"]}']
                    }

        # 3. New Alpha Entry
        if len(self.positions) < self.max_positions:
            for sym, p in prices.items():
                if sym in self.positions: continue
                
                stats = self._analyze(sym)
                if not stats: continue
                
                # Mutation: Only enter if price is "inefficient" (over-extended)
                # and hits extreme Z-score/RSI exhaustion.
                if stats['z'] < self.z_entry_threshold and \
                   stats['rsi'] < self.rsi_oversold and \
                   stats['eff'] < self.efficiency_threshold:
                    
                    self.positions[sym] = {
                        'qty': self.base_amount,
                        'avg_price': p,
                        'dca_level': 0,
                        'peak_price': p
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': self.base_amount,
                        'reason': ['OMEGA_ENTRY', f'Z_{stats["z"]:.2f}']
                    }

        return {}