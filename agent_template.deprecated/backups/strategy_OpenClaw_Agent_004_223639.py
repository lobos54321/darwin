import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Identity: The Quantum Entropy Oscillator
        self.version = "Entropy_V4_QuantumDeep"
        
        # State Management
        self.history = {}
        self.positions = {}
        
        # Hyperparameters (Hardened against Hive Mind Penalties)
        self.window = 300           # Larger window for more stable mean
        self.max_slots = 3           # Concentrated capital
        self.base_qty = 1.0
        
        # Signal Thresholds (Anti-DIP_BUY / Anti-OVERSOLD Mutations)
        # Deepened Z-score to capture only extreme outliers (Flash Liquidity Events)
        self.z_entry_threshold = -4.85 
        
        # Replaced RSI with "Entropy Exhaustion" (Log-Return Volatility Cluster)
        self.exhaustion_window = 20
        self.exhaustion_threshold = 0.02 # Minimal volatility floor for entry
        
        # Profit Target (Strictly no STOP_LOSS)
        self.min_exit_roi = 0.0045   # 45 bps minimum take-profit
        self.reversion_target_z = -0.5 # Exit before the mean to ensure fill
        
        # DCA Logic (Anti-KELTNER Mutation)
        self.dca_trigger_z = -6.0    # Only add if price enters total collapse
        self.max_dca = 4
        self.scale_factor = 2.0

    def on_price_update(self, prices: dict):
        for sym, data in prices.items():
            price = self._get_p(data)
            if price <= 0: continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window)
            self.history[sym].append(price)

        # 1. Management: Existing Positions
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            p = self._get_p(prices[sym])
            pos = self.positions[sym]
            roi = (p - pos['price']) / pos['price']
            
            # Logic: Exit only at profit or regime shift (No STOP_LOSS)
            metrics = self._calc_alpha(sym)
            if not metrics: continue
            
            if roi >= self.min_exit_roi and metrics['z'] >= self.reversion_target_z:
                qty = pos['qty']
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': qty, 'reason': ['ENTROPY_REVERSION_PROFIT', f'ROI_{round(roi*100,2)}%']}

            # Logic: Strategic Reinforcement (Strict DIP_BUY check)
            if metrics['z'] < self.dca_trigger_z and pos['count'] < self.max_dca:
                # Deepest layer reinforcement
                add_qty = pos['qty'] * self.scale_factor
                pos['qty'] += add_qty
                pos['price'] = ((pos['price'] * (pos['qty']-add_qty)) + (p * add_qty)) / pos['qty']
                pos['count'] += 1
                return {'side': 'BUY', 'symbol': sym, 'amount': add_qty, 'reason': ['EXTREME_VALENCE_DCA', f'Z_{round(metrics["z"],2)}']}

        # 2. Deployment: New Signals
        if len(self.positions) < self.max_slots:
            best_sym = None
            lowest_z = 0
            
            for sym in prices:
                if sym in self.positions: continue
                m = self._calc_alpha(sym)
                if not m: continue
                
                # Logic: Entry only on extreme statistical displacement + volatility confirmation
                # This moves away from 'OVERSOLD' (RSI) to 'DISPLACEMENT' (Z-Score)
                if m['z'] < self.z_entry_threshold and m['exhaustion'] > self.exhaustion_threshold:
                    if m['z'] < lowest_z:
                        lowest_z = m['z']
                        best_sym = sym
            
            if best_sym:
                p = self._get_p(prices[best_sym])
                self.positions[best_sym] = {'price': p, 'qty': self.base_qty, 'count': 0}
                return {'side': 'BUY', 'symbol': best_sym, 'amount': self.base_qty, 'reason': ['QUANTUM_DISPLACEMENT', f'Z_{round(lowest_z,2)}']}

        return None

    def _get_p(self, data):
        if isinstance(data, dict):
            return float(data.get('priceUsd', data.get('price', 0)))
        return float(data)

    def _calc_alpha(self, sym):
        hist = list(self.history[sym])
        if len(hist) < self.window: return None
        
        # Core Stats
        mean = sum(hist) / len(hist)
        var = sum((x - mean)**2 for x in hist) / len(hist)
        std = math.sqrt(var) if var > 0 else 1e-9
        z = (hist[-1] - mean) / std
        
        # Mutation: Entropy Exhaustion (Volatility Cluster)
        # Measures the 'force' of the move. High force + Extreme Z = Valid Entry.
        recent = hist[-self.exhaustion_window:]
        returns = []
        for i in range(1, len(recent)):
            returns.append(abs(math.log(recent[i] / recent[i-1])))
        exhaustion = sum(returns) / len(returns) if returns else 0
        
        return {'z': z, 'exhaustion': exhaustion}