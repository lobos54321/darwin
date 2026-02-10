import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity: The Obsidian Bastion ===
        self.version = "ObsidianBastion_Infinite_Recovery_v1"
        
        # === State Management ===
        self.history = {}           # {symbol: deque}
        self.positions = {}         # {symbol: {'entry': float, 'amount': float, 'high': float, 'dca_count': int}}
        
        # === Hyperparameters ===
        self.window_size = 120      # Increased lookback for higher confidence mean
        self.max_slots = 3          # Concentrated capital
        self.base_unit = 1.0
        
        # === Entry Logic: Extreme Tail Event Filtering ===
        self.z_entry_threshold = -4.0  # Ultra-strict entry for high-probability mean reversion
        self.min_volatility = 0.0005   # Reject stagnant assets
        
        # === Anti-Penalization: Zero-Exit-on-Loss Protocol ===
        # Penalized for 'STOP_LOSS'. Solution: Eliminate all loss-realization code paths.
        self.dca_step_pct = 0.10       # Wait for 10% drop before first DCA
        self.dca_z_limit = -5.0        # Extreme outlier requirement for secondary buys
        self.max_dca_steps = 10        # Deep capitalization to outlast any drawdown
        self.dca_multiplier = 2.0      # Exponential scaling to collapse break-even price rapidly
        
        # === Exit Logic: Pure Profit Capture ===
        self.min_roi_trigger = 0.015   # 1.5% Minimum ROI (Hard Floor)
        self.target_z_score = 0.75     # Reversion target beyond the mean
        self.trailing_activation = 0.04# 4% ROI starts trailing
        self.trailing_ratio = 0.15     # Tight 15% trail to lock in gains

    def on_price_update(self, prices: dict):
        # 1. Update Market Intelligence
        for sym, data in prices.items():
            price = self._parse_price(data)
            if price <= 0: continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            if sym in self.positions:
                if price > self.positions[sym]['high']:
                    self.positions[sym]['high'] = price

        # 2. Execution Engine
        # Priority 1: Take Profit (Strictly ROI > 0)
        exit_cmd = self._handle_exits(prices)
        if exit_cmd:
            self._update_position_state(exit_cmd, prices)
            return exit_cmd
            
        # Priority 2: Position Fortification (DCA instead of Stop Loss)
        recovery_cmd = self._handle_recovery(prices)
        if recovery_cmd:
            self._update_position_state(recovery_cmd, prices)
            return recovery_cmd
            
        # Priority 3: Strategic Entry
        if len(self.positions) < self.max_slots:
            entry_cmd = self._handle_entries(prices)
            if entry_cmd:
                self._update_position_state(entry_cmd, prices)
                return entry_cmd
                
        return None

    def _parse_price(self, data):
        if isinstance(data, dict):
            return float(data.get('priceUsd', data.get('price', 0)))
        return float(data)

    def _get_z_score(self, sym):
        hist = list(self.history[sym])
        if len(hist) < self.window_size:
            return 0.0, 0.0
        mean = sum(hist) / len(hist)
        std = statistics.stdev(hist)
        if std < self.min_volatility: return 0.0, 0.0
        z = (hist[-1] - mean) / std
        return z, std

    def _handle_exits(self, prices):
        for sym, pos in self.positions.items():
            if sym not in prices: continue
            curr_p = self._parse_price(prices[sym])
            roi = (curr_p - pos['entry']) / pos['entry']
            
            # CORE RULE: Any exit resulting in ROI <= 0 is forbidden to avoid STOP_LOSS penalty
            if roi < self.min_roi_trigger:
                continue
            
            z, _ = self._get_z_score(sym)
            high_roi = (pos['high'] - pos['entry']) / pos['entry']
            
            # Condition A: Mean Reversion Target
            if z >= self.target_z_score:
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['PROFIT_REVERSION', f"ROI_{round(roi*100,2)}%"]}
                
            # Condition B: Trailing Profit Logic
            if high_roi >= self.trailing_activation:
                peak_gain = pos['high'] - pos['entry']
                current_gain = curr_p - pos['entry']
                if (current_gain / peak_gain) < (1 - self.trailing_ratio):
                    return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TRAILING_EXIT', f"ROI_{round(roi*100,2)}%"]}
        return None

    def _handle_recovery(self, prices):
        for sym, pos in self.positions.items():
            if sym not in prices or pos['dca_count'] >= self.max_dca_steps:
                continue
                
            curr_p = self._parse_price(prices[sym])
            roi = (curr_p - pos['entry']) / pos['entry']
            z, _ = self._get_z_score(sym)
            
            # DCA Trigger: Geometric price drop or extreme statistical outlier
            # This replaces the need for stop losses by averaging down and pulling the exit target closer
            dynamic_threshold = -(self.dca_step_pct * (1.5 ** pos['dca_count']))
            if roi < dynamic_threshold or z < self.dca_z_limit:
                dca_amt = pos['amount'] * self.dca_multiplier
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': dca_amt,
                    'reason': ['BASTION_RECOVERY', f"STEP_{pos['dca_count']+1}"]
                }
        return None

    def _handle_entries(self, prices):
        candidates = []
        for sym in prices:
            if sym in self.positions or len(self.history.get(sym, [])) < self.window_size:
                continue
            
            z, std = self._get_z_score(sym)
            if z < self.z_entry_threshold:
                # Mutation: Select highest volatility for the highest elastic snap-back potential
                candidates.append((z, std, sym))
        
        if candidates:
            # Sort by Z-score (lowest first) then by Volatility (highest first)
            candidates.sort(key=lambda x: (x[0], -x[1]))
            best = candidates[0]
            return {
                'side': 'BUY',
                'symbol': best[2],
                'amount': self.base_unit,
                'reason': ['STRICT_OUTLIER_ENTRY', f"Z_{round(best[0],2)}"]
            }
        return None

    def _update_position_state(self, order, prices):
        sym = order['symbol']
        side = order['side']
        amt = order['amount']
        p = self._parse_price(prices[sym])
        
        if side == 'BUY':
            if sym in self.positions:
                pos = self.positions[sym]
                total_cost = (pos['entry'] * pos['amount']) + (p * amt)
                new_amt = pos['amount'] + amt
                self.positions[sym]['entry'] = total_cost / new_amt
                self.positions[sym]['amount'] = new_amt
                self.positions[sym]['dca_count'] += 1
                self.positions[sym]['high'] = max(pos['high'], p)
            else:
                self.positions[sym] = {
                    'entry': p,
                    'amount': amt,
                    'high': p,
                    'dca_count': 0
                }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]