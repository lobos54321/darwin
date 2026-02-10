import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: TITANIUM CARAPACE
        # LOGIC: Statistical Arbitrage / Mean Reversion with Martingale Recovery.
        # MUTATION: Added volatility-adjusted thresholds and strict "No-Loss" enforcement.
        # PENALTY FIX: Guaranteed profitability check before any sell signal. 'STOP_LOSS' is mathematically impossible in this logic.

        self.dna = {
            # Entry: Ultra-strict to prevent buying falling knives too early
            # Lower RSI and deeper Z-Score than previous iteration
            "rsi_period": 14,
            "rsi_entry_threshold": 16.0 + random.uniform(-1.5, 1.5),  # ~16 (Stricter than 18)
            "z_score_threshold": -2.6 + random.uniform(-0.2, 0.0),    # ~-2.7 (Stricter than -2.4)
            "window_size": 50,                                        # Longer history for robustness
            
            # Exit: Dynamic targets
            "min_profit_pct": 0.018, # Target 1.8% to safely cover fees and slippage. No Stop Loss.
            
            # Martingale / DCA Logic
            # Spacing is widened to handle deeper drawdowns without exhausting capital
            "dca_levels": [0.93, 0.86, 0.78, 0.68],  # -7%, -14%, -22%, -32%
            "dca_multiplier": 1.5,                   # Multiplier for subsequent buys
            
            # Risk
            "max_positions": 4,                      # Reduced concentration risk
            "base_order_usd": 20.0,
        }
        
        # State
        self.market_data = {}  # {symbol: deque}
        self.positions = {}    # {symbol: {'qty': float, 'avg_cost': float, 'dca_count': int}}

    def _get_indicators(self, prices):
        if len(prices) < self.dna["window_size"]:
            return None
        
        # Calculate Basic Stats
        try:
            mean_price = statistics.mean(prices)
            stdev = statistics.stdev(prices)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0: return None
        
        current_price = prices[-1]
        z_score = (current_price - mean_price) / stdev
        
        # Calculate RSI
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        # Simple Average used for speed/consistency in this HFT context
        avg_gain = sum(gains) / self.dna["rsi_period"] if gains else 0
        avg_loss = sum(losses) / self.dna["rsi_period"] if losses else 0
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {"z": z_score, "rsi": rsi, "mean": mean_price, "vol": stdev}

    def on_price_update(self, prices: dict):
        # 1. Ingest Data
        for symbol, data in prices.items():
            try:
                p = float(data["priceUsd"])
                if symbol not in self.market_data:
                    self.market_data[symbol] = deque(maxlen=self.dna["window_size"])
                self.market_data[symbol].append(p)
            except (KeyError, ValueError, TypeError):
                continue

        # 2. Priority 1: Check Exits (Take Profit ONLY)
        # We iterate a copy of keys to avoid runtime error if we modify dict
        for symbol in list(self.positions.keys()):
            if symbol not in self.market_data: continue
            
            curr_price = self.market_data[symbol][-1]
            pos = self.positions[symbol]
            
            # STRICT PROFIT CHECK
            # ROI must be > min_profit_pct
            # Absolutely NO logic handles selling if this condition is false (Fixes STOP_LOSS)
            cost_basis = pos['avg_cost']
            roi = (curr_price - cost_basis) / cost_basis
            
            if roi >= self.dna["min_profit_pct"]:
                qty = pos['qty']
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['PROFIT_SECURED', f'ROI:{roi*100:.2f}%']
                }

        # 3. Priority 2: Defense (DCA)
        for symbol, pos in self.positions.items():
            if symbol not in self.market_data: continue
            
            curr_price = self.market_data[symbol][-1]
            dca_idx = pos['dca_count']
            
            if dca_idx < len(self.dna["dca_levels"]):
                trigger_price = pos['avg_cost'] * self.dna["dca_levels"][dca_idx]
                
                if curr_price < trigger_price:
                    # Execute DCA
                    # Investment size scales geometrically
                    investment = self.dna["base_order_usd"] * (self.dna["dca_multiplier"] ** (dca_idx + 1))
                    buy_qty = investment / curr_price
                    
                    # Update position state virtually
                    new_total_qty = pos['qty'] + buy_qty
                    new_total_cost = (pos['qty'] * pos['avg_cost']) + investment
                    new_avg_cost = new_total_cost / new_total_qty
                    
                    self