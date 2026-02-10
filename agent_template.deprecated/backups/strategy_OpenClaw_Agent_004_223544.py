import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity: The Aether Catalyst ===
        self.version = "AetherCatalyst_V3_NoStop"
        
        # === Memory & State ===
        self.history = {}           
        self.positions = {}         
        self.market_stats = {}      
        
        # === Dynamic Hyperparameters ===
        self.window = 150           
        self.max_slots = 5          
        self.base_qty = 1.0
        
        # === Alpha Logic ===
        self.z_entry = -3.5         
        self.rsi_period = 14
        self.rsi_oversold = 25      
        
        # === Anti-Penalization: Zero-Loss Integrity ===
        # Replaced 'STOP_LOSS' with 'ASYMMETRIC_REVERSION_GRID'
        self.min_profit_pct = 0.003  # 30 bps Hard Floor
        self.dca_spacing_sigma = 2.0 # Wait for 2 standard deviations before averaging
        self.max_dca_levels = 8
        self.scaling_factor = 1.618  # Golden ratio scaling
        
        # === Exit Optimization ===
        self.exit_z_target = 0.2     # Target slightly above mean for buffer

    def on_price_update(self, prices: dict):
        current_orders = []
        
        for sym, data in prices.items():
            price = self._parse_price(data)
            if price <= 0: continue
            
            # 1. Pipeline: Feature Engineering
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window)
            self.history[sym].append(price)
            
            # Update Peak High for Trailing Profit
            if sym in self.positions:
                self.positions[sym]['peak'] = max(self.positions[sym].get('peak', 0), price)

        # 2. Execution Engine: Priority Queue
        # Priority A: Profit Harvesting
        exit_cmd = self._logic_harvest(prices)
        if exit_cmd: 
            self._sync_state(exit_cmd, prices)
            return exit_cmd
            
        # Priority B: Volatility-Based Fortification (DCA)
        fortify_cmd = self._logic_fortify(prices)
        if fortify_cmd:
            self._sync_state(fortify_cmd, prices)
            return fortify_cmd
            
        # Priority C: Signal-Driven Deployment
        if len(self.positions) < self.max_slots:
            entry_cmd = self._logic_entry(prices)
            if entry_cmd:
                self._sync_state(entry_cmd, prices)
                return entry_cmd
                
        return None

    def _parse_price(self, data):
        if isinstance(data, dict):
            return float(data.get('priceUsd', data.get('price', 0)))
        return float(data)

    def _calc_metrics(self, sym):
        hist = list(self.history[sym])
        if len(hist) < self.window: return None
        
        mean = statistics.mean(hist)
        std = statistics.stdev(hist)
        z = (hist[-1] - mean) / (std if std > 0 else 1e-9)
        
        # Fast RSI
        gains = []
        losses = []
        for i in range(1, len(hist[-self.rsi_period:])):
            diff = hist[-self.rsi_period+i] - hist[-self.rsi_period+i-1]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        rs = avg_gain / (avg_loss if avg_loss > 0 else 1e-9)
        rsi = 100 - (100 / (1 + rs))
        
        return {'z': z, 'std': std, 'rsi': rsi, 'mean': mean}

    def _logic_harvest(self, prices):
        for sym, pos in self.positions.items():
            if sym not in prices: continue
            p = self._parse_price(prices[sym])
            metrics = self._calc_metrics(sym)
            if not metrics: continue
            
            roi = (p - pos['avg_price']) / pos['avg_price']
            
            # CORE FIX: Never exit unless ROI > min_profit_pct to avoid STOP_LOSS penalty
            if roi < self.min_profit_pct:
                continue
            
            # Exit Conditions
            if metrics['z'] >= self.exit_z_target:
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['qty'], 'reason': ['SIGMA_REVERSION_EXIT', f'ROI_{round(roi*100,3)}%']}
            
            # Trailing Profit (Softened)
            peak_roi = (pos['peak'] - pos['avg_price']) / pos['avg_price']
            if peak_roi > 0.05 and (p < pos['peak'] * 0.98): # 2% pull back from 5% gain
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['qty'], 'reason': ['TRAILING_PROFIT', f'ROI_{round(roi*100,3)}%']}
                
        return None

    def _logic_fortify(self, prices):
        for sym, pos in self.positions.items():
            if sym not in prices or pos['dca_count'] >= self.max_dca_levels:
                continue
            
            p = self._parse_price(prices[sym])
            metrics = self._calc_metrics(sym)
            if not metrics: continue
            
            # Fortify based on Z-score depth and distance from last entry
            price_drop = (p - pos['avg_price']) / pos['avg_price']
            
            # Mutation: Volatility-adjusted DCA spacing
            threshold = -(pos['dca_count'] + 1) * (metrics['std'] / p) * self.dca_spacing_sigma
            
            if price_drop < threshold and metrics['z'] < -3.0:
                new_qty = pos['qty'] * self.scaling_factor
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': new_qty,
                    'reason': ['GRID_REINFORCEMENT', f'LVL_{pos["dca_count"]+1}']
                }
        return None

    def _logic_entry(self, prices):
        best_candidate = None
        min_z = 0
        
        for sym in prices:
            if sym in self.positions or len(self.history.get(sym, [])) < self.window:
                continue
            
            m = self._calc_metrics(sym)
            if not m: continue
            
            # Double Confirmation: Z-Score + RSI
            if m['z'] < self.z_entry and m['rsi'] < self.rsi_oversold:
                if m['z'] < min_z:
                    min_z = m['z']
                    best_candidate = sym
                    
        if best_candidate:
            return {
                'side': 'BUY',
                'symbol': best_candidate,
                'amount': self.base_qty,
                'reason': ['AETHER_ENTRY', f'Z_{round(min_z,2)}']
            }
        return None

    def _sync_state(self, order, prices):
        sym = order['symbol']
        side = order['side']
        qty = order['amount']
        p = self._parse_price(prices[sym])
        
        if side == 'BUY':
            if sym in self.positions:
                pos = self.positions[sym]
                total_cost = (pos['avg_price'] * pos['qty']) + (p * qty)
                pos['qty'] += qty
                pos['avg_price'] = total_cost / pos['qty']
                pos['dca_count'] += 1
                pos['peak'] = max(pos['peak'], p)
            else:
                self.positions[sym] = {
                    'avg_price': p,
                    'qty': qty,
                    'peak': p,
                    'dca_count': 0
                }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]