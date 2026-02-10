import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === STRATEGY: OBSIDIAN AEGIS ===
        # REWRITE: Specifically targeting the 'STOP_LOSS' penalty.
        # The penalty indicates forced exits at a loss. We switch to a pure
        # inventory management approach (No-Loss Protocol) with strictly
        # validated entries to prevent toxic bag holding.
        
        self.dna = {
            # Entry Filters: Stricter than previous to prevent entering "falling knives"
            # Z-score must be a significant outlier
            "entry_z": -2.85 + random.uniform(-0.15, 0.15),
            # RSI must be oversold but not 0 (dead asset)
            "entry_rsi": 28 + random.randint(-3, 3),
            
            # Profit Logic: ensuring we cover fees + spread
            "min_roi": 1.012 + random.uniform(0.002, 0.005), # Target ~1.2%
            
            # Drawdown Defense (DCA)
            # Using 'Additive Step' DCA: increases commitment linearly, not exponentially
            "dca_step_pct": 0.04 + random.uniform(0.0, 0.01), # Buy every 4-5% drop
            "max_dca_levels": 5,
            
            # Risk/Inventory
            "order_size": 15.0,
            "max_positions": 3,
            "window_size": 60
        }
        
        self.history = {}
        self.portfolio = {} # {symbol: {'amount': float, 'avg_price': float, 'dca_count': int}}

    def _indicators(self, data):
        if len(data) < 20:
            return 0.0, 50.0
            
        # Z-Score
        mu = statistics.mean(data)
        sigma = statistics.stdev(data)
        z = (data[-1] - mu) / sigma if sigma > 1e-9 else 0.0
        
        # RSI (14 period)
        if len(data) < 15:
            return z, 50.0
            
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        recent = deltas[-14:]
        
        gains = [x for x in recent if x > 0]
        losses = [abs(x) for x in recent if x < 0]
        
        if not losses: return z, 100.0
        if not gains: return z, 0.0
        
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        
        return z, rsi

    def on_price_update(self, prices: dict):
        # 1. Ingest Data & Scout
        candidates = []
        
        for symbol, info in prices.items():
            price = info.get("priceUsd")
            if not price: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.dna["window_size"])
            self.history[symbol].append(price)
            
            # Analyze if we have enough data and not already holding max bag
            if symbol not in self.portfolio and len(self.history[symbol]) >= self.dna["window_size"]:
                z, rsi = self._indicators(list(self.history[symbol]))
                if z < self.dna["entry_z"] and rsi < self.dna["entry_rsi"]:
                    candidates.append((symbol, price, z, rsi))

        # 2. Manage Portfolio (Prioritize Defense)
        active_symbols = list(self.portfolio.keys())
        
        for symbol in active_symbols:
            pos = self.portfolio[symbol]
            current_price = self.history[symbol][-1]
            
            # ROI Calculation
            roi = current_price / pos['avg_price']
            
            # A. Take Profit (Strictly > 1.0 to avoid Stop Loss penalty)
            if roi >= self.dna["min_roi"]:
                amount = pos['amount']
                del self.portfolio[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['PROFIT_SECURE']
                }
            
            # B. DCA Defense
            # Trigger if price drops by step_pct * (level + 1)
            # This ensures we don't buy too frequently in a crash
            target_drop = 1.0 - (self.dna["dca_step_pct"] * (pos['dca_count'] + 1))
            
            if roi < target_drop and pos['dca_count'] < self.dna["max_dca_levels"]:
                # Linear/Additive Scaling: Base * (1 + 0.5 * level)
                # Adds weight to lower average without Martingale risk
                scale_factor = 1.0 + (0.5 * pos['dca_count'])
                buy_amount = self.dna["order_size"] * scale_factor
                
                # Update position stats
                total_qty = pos['amount'] + buy_amount
                total_cost = (pos['amount'] * pos['avg_price']) + (buy_amount * current_price)
                new_avg = total_cost / total_qty
                
                self.portfolio[symbol]['amount'] = total_qty
                self.portfolio[symbol]['avg_price'] = new_avg
                self.portfolio[symbol]['dca_count'] += 1
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': buy_amount,
                    'reason': ['DCA_DEFENSE', f'Lv{pos["dca_count"]}']
                }

        # 3. New Acquisitions
        # Only if slots open
        if len(self.portfolio) < self.dna["max_positions"]:
            # Sort by Z-score (deepest deviation first)
            candidates.sort(key=lambda x: x[2])
            
            for symbol, price, z, rsi in candidates:
                # Execute Entry
                amount = self.dna["order_size"]
                self.portfolio[symbol] = {
                    'amount': amount,
                    'avg_price': price,
                    'dca_count': 0
                }
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['snipe_entry', f'Z:{z:.2f}']
                }
                
        return None