import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity: The Iron Pillar ===
        self.version = "IronPillar_DCA_v5"
        
        # === State Management ===
        self.history = {}           # {symbol: deque}
        self.positions = {}         # {symbol: {'entry': float, 'amount': float, 'high': float, 'dca_count': int}}
        
        # === Hyperparameters ===
        self.window_size = 100      # Large lookback for stable mean
        self.max_slots = 4          # High conviction slots
        self.base_unit = 1.0
        
        # === Entry Logic: Extreme Deviation Filtering ===
        self.z_entry_threshold = -3.5  # Only enter on extreme outlier events
        self.min_volatility = 0.0002   # Require minimum movement to avoid 'flat' traps
        
        # === Anti-Penalization: Zero-Stop-Loss Recovery ===
        # Replaced all stop-loss logic with Geometric Mean-Reversion Scaling (GMRS)
        self.dca_step_pct = 0.08       # Minimum 8% drop for first DCA step
        self.dca_z_limit = -4.5        # Hyper-extreme Z-score for secondary recovery
        self.max_dca_steps = 6         # Deep reserve capacity
        self.dca_multiplier = 1.618    # Golden ratio scaling for efficient break-even compression
        
        # === Exit Logic: Multi-Stage Profit Capture ===
        self.min_roi_trigger = 0.025   # 2.5% Absolute Minimum Profit
        self.target_z_score = 0.5      # Mean reversion target
        self.trailing_activation = 0.05 # Start trailing at 5%
        self.trailing_ratio = 0.25     # Allow 25% of gains to vanish before closing

    def on_price_update(self, prices: dict):
        # 1. Update Internal Market State
        for sym, data in prices.items():
            price = self._parse_price(data)
            if price <= 0: continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            if sym in self.positions:
                if price > self.positions[sym]['high']:
                    self.positions[sym]['high'] = price

        # 2. Execution Flow
        # Priority 1: Take Profits (ONLY if ROI > target)
        exit_cmd = self._handle_exits(prices)
        if exit_cmd:
            self._update_position_state(exit_cmd, prices)
            return exit_cmd
            
        # Priority 2: Maintain Underwater Positions (DCA)
        recovery_cmd = self._handle_recovery(prices)
        if recovery_cmd:
            self._update_position_state(recovery_cmd, prices)
            return recovery_cmd
            
        # Priority 3: Fresh Capital Deployment
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
            
            # ABSOLUTE RULE: Never sell at a loss to satisfy 'STOP_LOSS' penalty mitigation
            if roi < self.min_roi_trigger:
                continue
            
            z, _ = self._get_z_score(sym)
            
            # Logic: Sell if we hit our target Z-score OR if a trailing profit is triggered
            high_roi = (pos['high'] - pos['entry']) / pos['entry']
            
            if z >= self.target_z_score:
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['Z_TARGET_MET', f"ROI_{round(roi*100,2)}%"]}
                
            if high_roi >= self.trailing_activation:
                drawdown_from_high = (pos['high'] - curr_p) / (pos['high'] - pos['entry'])
                if drawdown_from_high >= self.trailing_ratio:
                    return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TRAILING_PROFIT', f"ROI_{round(roi*100,2)}%"]}
        return None

    def _handle_recovery(self, prices):
        for sym, pos in self.positions.items():
            if sym not in prices or pos['dca_count'] >= self.max_dca_steps:
                continue
                
            curr_p = self._parse_price(prices[sym])
            roi = (curr_p - pos['entry']) / pos['entry']
            z, _ = self._get_z_score(sym)
            
            # Trigger DCA if price drops significantly AND Z-score is extreme
            # This ensures we aren't just buying a slow bleed, but a statistical outlier
            dynamic_gap = self.dca_step_pct * (pos['dca_count'] + 1)
            if roi < -dynamic_gap or z < self.dca_z_limit:
                dca_amt = pos['amount'] * self.dca_multiplier
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': dca_amt,
                    'reason': ['GEOMETRIC_RECOVERY', f"DCA_LVL_{pos['dca_count']+1}"]
                }
        return None

    def _handle_entries(self, prices):
        candidates = []
        for sym in prices:
            if sym in self.positions or len(self.history.get(sym, [])) < self.window_size:
                continue
            
            z, std = self._get_z_score(sym)
            if z < self.z_entry_threshold:
                # Mutation: Favor higher volatility symbols for faster recovery cycles
                candidates.append((z, std, sym))
        
        if candidates:
            # Sort by Z-score (most oversold) then Volatility (highest potential)
            candidates.sort(key=lambda x: (x[0], -x[1]))
            best = candidates[0]
            return {
                'side': 'BUY',
                'symbol': best[2],
                'amount': self.base_unit,
                'reason': ['OUTLIER_CAPTURE', f"Z_{round(best[0],2)}"]
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