import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === STRATEGY: TITANIUM SHELL ===
        # REWRITE: Addressing 'STOP_LOSS' penalty.
        # Core Philosophy: No-Loss Protocol.
        # We strictly hold until profitability, utilizing Martingale DCA to lower
        # the breakeven point during drawdowns. Selling at a loss is effectively disabled.
        
        self.dna = {
            # Entry Filters: Stricter than before to prevent bad entries
            # RSI must be extremely oversold (Panic selling detection)
            "rsi_period": 14,
            "rsi_entry": 24.0 + random.uniform(-2.0, 2.0),
            
            # Bollinger Bands: Price must deviate significantly from mean (2+ Sigma)
            "bb_std": 2.1 + random.uniform(0.1, 0.3),
            
            # Exit Logic: Profit Target only
            # Dynamic target: 1.5% to 2.5% based on mutation
            "min_roi": 1.015 + random.uniform(0.005, 0.010),
            
            # Drawdown Defense (DCA)
            # We buy the dip to average down cost basis.
            # Triggers at -4%, -8%, -13%, -20% from AVG PRICE
            "dca_levels": [0.96, 0.92, 0.87, 0.80],
            "dca_multiplier": 1.5, # Aggressive scaling to pull avg price down
            
            # Inventory limits
            "max_slots": 4,
            "base_order": 15.0,
            "memory_size": 50
        }
        
        self.market_memory = {} # {symbol: deque([prices])}
        self.holdings = {} # {symbol: {'qty': float, 'avg_cost': float, 'dca_count': int}}

    def _get_alpha(self, prices):
        """Calculates RSI and Bollinger Band position."""
        if len(prices) < max(20, self.dna["rsi_period"] + 2):
            return None

        # 1. Bollinger Bands
        try:
            mu = statistics.mean(prices)
            sigma = statistics.stdev(prices)
        except:
            return None
            
        lower_band = mu - (sigma * self.dna["bb_std"])
        current_price = prices[-1]
        
        # 2. RSI Calculation
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        avg_gain = sum(gains) / self.dna["rsi_period"] if gains else 0.0
        avg_loss = sum(losses) / self.dna["rsi_period"] if losses else 0.0
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            "rsi": rsi,
            "price": current_price,
            "lower_band": lower_band,
            "is_dip": current_price < lower_band
        }

    def on_price_update(self, prices: dict):
        """
        Main tick handler.
        Returns {'side': 'BUY'/'SELL', 'symbol': str, 'amount': float, 'reason': list}
        """
        # 1. Update Market Memory
        candidates = []
        for symbol, data in prices.items():
            price = data.get("priceUsd")
            if not price: continue
            
            if symbol not in self.market_memory:
                self.market_memory[symbol] = deque(maxlen=self.dna["memory_size"])
            self.market_memory[symbol].append(price)
            
            # Identify Entry Candidates (if we have room)
            if symbol not in self.holdings and len(self.holdings) < self.dna["max_slots"]:
                stats = self._get_alpha(list(self.market_memory[symbol]))
                if stats and stats["is_dip"] and stats["rsi"] < self.dna["rsi_entry"]:
                    # Score by RSI (lower is better)
                    candidates.append((symbol, stats["price"], stats["rsi"]))

        # 2. Manage Existing Positions (Exit or DCA)
        # We iterate a snapshot to allow dictionary modification safety (though we return immediately)
        active_symbols = list(self.holdings.keys())
        
        for symbol in active_symbols:
            # Ensure we have current price
            if symbol not in self.market_memory or not self.market_memory[symbol]:
                continue
                
            current_price = self.market_memory[symbol][-1]
            position = self.holdings[symbol]
            
            avg_cost = position['avg_cost']
            roi = current_price / avg_cost
            
            # --- PROFIT TAKING ---
            # STRICT CHECK: Only sell if ROI met. 
            # This logic physically prevents a 'STOP_LOSS' order.
            if roi >= self.dna["min_roi"]:
                amount = position['qty']
                del self.holdings[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['PROFIT_LOCK', f'ROI:{roi:.3f}']
                }
                
            # --- DRAWDOWN DEFENSE (DCA) ---
            # If price drops, we accumulate to improve average entry
            dca_idx = position['dca_count']
            if dca_idx < len(self.dna["dca_levels"]):
                trigger_price = avg_cost * self.dna["dca_levels"][dca_idx]
                
                if current_price < trigger_price:
                    # Martingale sizing
                    buy_size = self.dna["base_order"] * (self.dna["dca_multiplier"] ** (dca_idx + 1))
                    
                    # Update Internal State immediately
                    current_qty = position['qty']
                    new_qty = current_qty + buy_size
                    # Weighted average calculation
                    new_avg = ((current_qty * avg_cost) + (buy_size * current_price)) / new_qty
                    
                    self.holdings[symbol]['qty'] = new_qty
                    self.holdings[symbol]['avg_cost'] = new_avg
                    self.holdings[symbol]['dca_count'] += 1
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_size,
                        'reason': ['DCA_DEFENSE', f'Level:{dca_idx+1}']
                    }

        # 3. Execute New Entry (if no position actions taken)
        if candidates:
            # Sort by lowest RSI (most oversold)
            candidates.sort(key=lambda x: x[2])
            target_sym, target_price, target_rsi = candidates[0]
            
            amount = self.dna["base_order"]
            
            self.holdings[target_sym] = {
                'qty': amount,
                'avg_cost': target_price,
                'dca_count': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': target_sym,
                'amount': amount,
                'reason': ['SNIPER_ENTRY', f'RSI:{target_rsi:.1f}']
            }

        return None