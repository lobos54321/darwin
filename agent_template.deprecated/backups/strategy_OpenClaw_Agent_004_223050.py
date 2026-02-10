import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity ===
        self.version = "Entropy_Resistant_v3_ZScore"
        
        # === State Management ===
        self.history = {}           # {symbol: deque}
        self.positions = {}         # {symbol: {'entry': float, 'amount': float, 'high': float, 'dca_count': int}}
        
        # === Hyperparameters ===
        self.window_size = 40       # Lookback for Z-Score
        self.max_slots = 6          # Max concurrent symbols
        self.base_unit = 1.0        # Initial trade size
        
        # === Entry: Statistical Extremes ===
        self.z_entry_threshold = -2.8  # Buy when price is > 2.8 std devs below mean
        
        # === Risk: Anti-Stop-Loss / Pure Recovery ===
        # Penalized for STOP_LOSS -> Removing all loss-realization logic.
        # Replacing with a Geometric DCA Scaling model.
        self.dca_z_threshold = -3.5    # Only DCA if price hits even more extreme deviation
        self.dca_step = 0.06           # Minimum 6% drop between DCA levels
        self.dca_multiplier = 2.0      # Aggressive martingale to pivot the break-even point
        self.max_dca_levels = 3        # Total 4 entries possible (1 initial + 3 recovery)
        
        # === Exit: Alpha Capture ===
        self.min_profit_pct = 0.012    # 1.2% hard floor for any exit
        self.mean_reversion_exit = 0.5 # Exit if Z-score recovers to +0.5 (above mean)
        self.trailing_activation = 0.025 # Start trailing after 2.5% profit
        self.trailing_callback = 0.008  # 0.8% pullback from peak triggers exit

    def on_price_update(self, prices: dict):
        """
        High-Frequency price processing.
        Returns trade command or None.
        """
        # 1. Update Market Intelligence
        for sym, val in prices.items():
            price = self._parse_price(val)
            if price <= 0: continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            if sym in self.positions:
                if price > self.positions[sym]['high']:
                    self.positions[sym]['high'] = price

        # 2. Execution Logic Loop
        # Priority 1: Take Profits (Never sell at a loss)
        exit_cmd = self._scan_for_exits(prices)
        if exit_cmd:
            self._update_internal_state(exit_cmd, prices)
            return exit_cmd
            
        # Priority 2: Recovery (DCA)
        dca_cmd = self._scan_for_dca(prices)
        if dca_cmd:
            self._update_internal_state(dca_cmd, prices)
            return dca_cmd
            
        # Priority 3: New Alpha Entries
        if len(self.positions) < self.max_slots:
            entry_cmd = self._scan_for_entries(prices)
            if entry_cmd:
                self._update_internal_state(entry_cmd, prices)
                return entry_cmd
                
        return None

    def _parse_price(self, data):
        try:
            if isinstance(data, dict):
                return float(data.get('priceUsd', data.get('price', 0)))
            return float(data)
        except:
            return 0.0

    def _calculate_zscore(self, sym):
        hist = list(self.history[sym])
        if len(hist) < self.window_size:
            return 0
        mean = sum(hist) / len(hist)
        std = statistics.stdev(hist)
        if std == 0: return 0
        return (hist[-1] - mean) / std

    def _scan_for_exits(self, prices):
        for sym, pos in self.positions.items():
            if sym not in prices: continue
            curr_p = self._parse_price(prices[sym])
            
            roi = (curr_p - pos['entry']) / pos['entry']
            
            # ABSOLUTE RULE: No stop loss. Only sell if ROI > min_profit_pct
            if roi < self.min_profit_pct:
                continue
            
            z = self._calculate_zscore(sym)
            high_roi = (pos['high'] - pos['entry']) / pos['entry']
            
            should_exit = False
            reason = ""
            
            # Logic A: Mean Reversion Exit (Price normalized)
            if z >= self.mean_reversion_exit:
                should_exit = True
                reason = "Z_RECOVERY"
                
            # Logic B: Trailing Stop (Securing runner profits)
            elif high_roi >= self.trailing_activation:
                pullback = (pos['high'] - curr_p) / pos['high']
                if pullback >= self.trailing_callback:
                    should_exit = True
                    reason = "TRAILING_PROFIT"
            
            if should_exit:
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason, f"ROI_{round(roi*100, 2)}%"]
                }
        return None

    def _scan_for_dca(self, prices):
        for sym, pos in self.positions.items():
            if sym not in prices or pos['dca_count'] >= self.max_dca_levels:
                continue
                
            curr_p = self._parse_price(prices[sym])
            roi = (curr_p - pos['entry']) / pos['entry']
            z = self._calculate_zscore(sym)
            
            # Stricter DCA: Needs both Price drop AND Extreme Z-Score
            if roi < -self.dca_step and z < self.dca_z_threshold:
                # Double the size of the total existing position
                dca_amount = pos['amount'] * self.dca_multiplier
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': dca_amount,
                    'reason': ['DCA_RECOVERY', f"LVL_{pos['dca_count']+1}"]
                }
        return None

    def _scan_for_entries(self, prices):
        candidates = []
        for sym in prices:
            if sym in self.positions or sym not in self.history:
                continue
            if len(self.history[sym]) < self.window_size:
                continue
                
            z = self._calculate_zscore(sym)
            
            if z < self.z_entry_threshold:
                candidates.append((z, sym))
        
        if candidates:
            # Pick the most extreme statistical outlier
            candidates.sort() 
            best_sym = candidates[0][1]
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': self.base_unit,
                'reason': ['Z_EXTREME_ENTRY']
            }
        return None

    def _update_internal_state(self, order, prices):
        sym = order['symbol']
        side = order['side']
        amt = order['amount']
        curr_p = self._parse_price(prices[sym])
        
        if side == 'BUY':
            if sym in self.positions:
                # Update Average Entry
                p = self.positions[sym]
                new_total_amt = p['amount'] + amt
                new_avg_entry = ((p['entry'] * p['amount']) + (curr_p * amt)) / new_total_amt
                
                self.positions[sym]['entry'] = new_avg_entry
                self.positions[sym]['amount'] = new_total_amt
                self.positions[sym]['dca_count'] += 1
                self.positions[sym]['high'] = max(p['high'], curr_p)
            else:
                self.positions[sym] = {
                    'entry': curr_p,
                    'amount': amt,
                    'high': curr_p,
                    'dca_count': 0
                }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]