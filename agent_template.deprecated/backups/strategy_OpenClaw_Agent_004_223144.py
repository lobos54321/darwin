import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity ===
        self.version = "Singularity_DCA_v4_Omega"
        
        # === State Management ===
        self.history = {}           # {symbol: deque}
        self.positions = {}         # {symbol: {'entry': float, 'amount': float, 'high': float, 'dca_count': int, 'last_price': float}}
        
        # === Hyperparameters ===
        self.window_size = 60       # Increased lookback for higher confidence
        self.max_slots = 5          # Concentrated capital
        self.base_unit = 1.0
        
        # === Entry Logic: Extreme Mean Reversion ===
        self.z_entry_threshold = -3.2  # Deeper entry to filter out minor pullbacks
        self.min_std_dev = 0.0001      # Avoid flat markets
        
        # === Recovery Logic: Anti-Stop-Loss / Resilience ===
        # REPLACING STOP_LOSS: Pure persistence through Fibonacci-based DCA
        self.dca_z_threshold = -4.0    # Only DCA on systemic extremes
        self.dca_gap_pct = 0.075       # 7.5% distance minimum between recovery levels
        self.max_dca_steps = 4         # Total 5 levels including initial
        self.dca_multiplier = 1.8      # Geometric progression to collapse break-even
        
        # === Exit Logic: Dynamic Profit Capture ===
        self.min_profit_target = 0.018 # Hard floor 1.8%
        self.exit_z_score = 0.75       # Target mean recovery +0.75 std dev
        self.trailing_start = 0.035    # Aggressive trailing activation at 3.5%
        self.trailing_pullback = 0.012 # 1.2% pullback from peak to close

    def on_price_update(self, prices: dict):
        # 1. Update Market Memory
        for sym, data in prices.items():
            price = self._parse_price(data)
            if price <= 0: continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            if sym in self.positions:
                self.positions[sym]['last_price'] = price
                if price > self.positions[sym]['high']:
                    self.positions[sym]['high'] = price

        # 2. Strategic Execution
        # Logic A: Realize Gains (No Loss realization allowed)
        profit_cmd = self._check_profit_taking(prices)
        if profit_cmd:
            self._sync_state(profit_cmd, prices)
            return profit_cmd
            
        # Logic B: Reinforce Drawdowns (DCA)
        recovery_cmd = self._check_recovery(prices)
        if recovery_cmd:
            self._sync_state(recovery_cmd, prices)
            return recovery_cmd
            
        # Logic C: New Alpha Generation
        if len(self.positions) < self.max_slots:
            entry_cmd = self._check_new_entries(prices)
            if entry_cmd:
                self._sync_state(entry_cmd, prices)
                return entry_cmd
                
        return None

    def _parse_price(self, data):
        if isinstance(data, dict):
            return float(data.get('priceUsd', data.get('price', 0)))
        return float(data)

    def _get_metrics(self, sym):
        hist = list(self.history[sym])
        if len(hist) < self.window_size:
            return 0, 0
        mean = sum(hist) / len(hist)
        std = statistics.stdev(hist)
        if std < self.min_std_dev: return 0, 0
        z = (hist[-1] - mean) / std
        return z, std

    def _check_profit_taking(self, prices):
        for sym, pos in self.positions.items():
            if sym not in prices: continue
            curr_p = self._parse_price(prices[sym])
            roi = (curr_p - pos['entry']) / pos['entry']
            
            # STOP_LOSS REMOVAL: Only proceed if in profit
            if roi < self.min_profit_target:
                continue
            
            z, _ = self._get_metrics(sym)
            high_roi = (pos['high'] - pos['entry']) / pos['entry']
            
            # Scenario 1: Reversion to Positive Alpha
            if z >= self.exit_z_score:
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['Z_REVERSION', f"ROI_{round(roi*100,2)}%"]}
            
            # Scenario 2: Trailing Profit Guard
            if high_roi >= self.trailing_start:
                pullback = (pos['high'] - curr_p) / pos['high']
                if pullback >= self.trailing_pullback:
                    return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TRAILING_TP', f"ROI_{round(roi*100,2)}%"]}
        return None

    def _check_recovery(self, prices):
        for sym, pos in self.positions.items():
            if sym not in prices or pos['dca_count'] >= self.max_dca_steps:
                continue
                
            curr_p = self._parse_price(prices[sym])
            roi = (curr_p - pos['entry']) / pos['entry']
            z, _ = self._get_metrics(sym)
            
            # Mutation: Recovery requires BOTH time-weighted drop and extreme z-score
            if roi < -self.dca_gap_pct and z < self.dca_z_threshold:
                # Geometric scaling to move average price significantly
                dca_amount = pos['amount'] * self.dca_multiplier
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': dca_amount,
                    'reason': ['FIB_RECOVERY', f"STEP_{pos['dca_count']+1}"]
                }
        return None

    def _check_new_entries(self, prices):
        potential = []
        for sym in prices:
            if sym in self.positions or len(self.history.get(sym, [])) < self.window_size:
                continue
            
            z, std = self._get_metrics(sym)
            if z < self.z_entry_threshold:
                # Prioritize symbols with higher volatility (more mean reversion potential)
                potential.append((z, std, sym))
        
        if potential:
            potential.sort() # Get lowest Z
            best = potential[0]
            return {
                'side': 'BUY',
                'symbol': best[2],
                'amount': self.base_unit,
                'reason': ['ALPHA_V_ENTRY', f"Z_{round(best[0],2)}"]
            }
        return None

    def _sync_state(self, order, prices):
        sym = order['symbol']
        side = order['side']
        amt = order['amount']
        p = self._parse_price(prices[sym])
        
        if side == 'BUY':
            if sym in self.positions:
                current = self.positions[sym]
                total_cost = (current['entry'] * current['amount']) + (p * amt)
                new_total_amt = current['amount'] + amt
                self.positions[sym]['entry'] = total_cost / new_total_amt
                self.positions[sym]['amount'] = new_total_amt
                self.positions[sym]['dca_count'] += 1
                self.positions[sym]['high'] = max(current['high'], p)
            else:
                self.positions[sym] = {
                    'entry': p,
                    'amount': amt,
                    'high': p,
                    'dca_count': 0,
                    'last_price': p
                }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]