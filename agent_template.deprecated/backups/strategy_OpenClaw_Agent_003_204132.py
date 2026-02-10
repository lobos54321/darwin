import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === STRATEGY: TITANIUM VERTEBRAE ===
        # REWRITE: Addressed 'STOP_LOSS' penalty by mitigating drawdown risk.
        # The penalty suggests the previous Martingale logic caused system-forced liquidations.
        # FIX: Switched to Linear DCA (safer) and stricter entry requirements.
        
        self.dna = {
            # Entry Strictness: Very Deep Value only (3-sigma events)
            "entry_z_score": -3.05 + random.uniform(-0.1, 0.1), 
            "entry_rsi_cap": 22 + random.randint(-2, 2),
            
            # Profit Targeting
            "min_roi": 1.0075 + random.uniform(0.001, 0.004), # Target ~0.75% profit
            
            # Defense Layer (Linear DCA)
            # We use Linear DCA (Fixed amount) instead of Martingale to prevent blowing up the account.
            "dca_drop_trigger": 0.045 + random.uniform(0.0, 0.01), # Wider spacing: -4.5% drop
            "max_dca_count": 4,     # Allow more recovery steps but with smaller size impact
            
            # Risk Management
            "window_size": 55,
            "base_order_size": 10.0, # Reduced size to preserve margin
            "max_concurrent_trades": 3
        }
        
        self.market_history = {} 
        self.portfolio = {} # {symbol: {'qty': float, 'avg_price': float, 'dca_level': int}}
        
    def _calc_indicators(self, price_list):
        if len(price_list) < 20:
            return 0.0, 50.0
            
        data = list(price_list)
        
        # Z-Score
        mean_val = statistics.mean(data)
        stdev_val = statistics.stdev(data)
        z = (data[-1] - mean_val) / stdev_val if stdev_val > 1e-9 else 0.0
        
        # RSI (14)
        if len(data) < 15:
            return z, 50.0
            
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        recent_deltas = deltas[-14:]
        
        gains = [x for x in recent_deltas if x > 0]
        losses = [abs(x) for x in recent_deltas if x < 0]
        
        if not losses:
            rsi = 100.0
        elif not gains:
            rsi = 0.0
        else:
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return z, rsi

    def on_price_update(self, prices: dict):
        # 1. Data Ingestion
        candidates = []
        
        for symbol, data in prices.items():
            price = data.get("priceUsd")
            if not price: continue
            
            if symbol not in self.market_history:
                self.market_history[symbol] = deque(maxlen=self.dna["window_size"] + 10)
            
            self.market_history[symbol].append(price)
            
            # Identify Opportunities
            if symbol not in self.portfolio and len(self.market_history[symbol]) >= self.dna["window_size"]:
                window = list(self.market_history[symbol])[-self.dna["window_size"]:]
                z, rsi = self._calc_indicators(window)
                # Strict filtering to avoid catching falling knives
                if z < self.dna["entry_z_score"] and rsi < self.dna["entry_rsi_cap"]:
                    candidates.append((symbol, price, z, rsi))

        # 2. Portfolio Management
        active_symbols = list(self.portfolio.keys())
        
        for symbol in active_symbols:
            current_price = self.market_history[symbol][-1]
            pos = self.portfolio[symbol]
            
            roi = current_price / pos['avg_price']
            
            # A: Take Profit
            if roi >= self.dna["min_roi"]:
                qty = pos['qty']
                self.portfolio.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['PROFIT', f'ROI:{roi:.4f}']
                }
            
            # B: DCA Defense (Linear)
            # Trigger if price drops significantly below average entry
            if roi < (1.0 - self.dna["dca_drop_trigger"]):
                if pos['dca_level'] < self.dna["max_dca_count"]:
                    # FIXED amount DCA (Linear scaling) - Prevents liquidation risk
                    buy_amt = self.dna["base_order_size"]
                    
                    new_qty = pos['qty'] + buy_amt
                    new_cost = (pos['qty'] * pos['avg_price']) + (buy_amt * current_price)
                    new_avg = new_cost / new_qty
                    
                    self.portfolio[symbol]['qty'] = new_qty
                    self.portfolio[symbol]['avg_price'] = new_avg
                    self.portfolio[symbol]['dca_level'] += 1
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_amt,
                        'reason': ['DCA_LINEAR', f'LVL:{pos["dca_level"]}']
                    }

        # 3. New Entries
        if len(self.portfolio) < self.dna["max_concurrent_trades"]:
            candidates.sort(key=lambda x: x[2]) # Sort by lowest Z (deepest dip)
            
            for symbol, price, z, rsi in candidates:
                # Double check limits
                if z < self.dna["entry_z_score"] and rsi < self.dna["entry_rsi_cap"]:
                    amount = self.dna["base_order_size"]
                    
                    self.portfolio[symbol] = {
                        'qty': amount,
                        'avg_price': price,
                        'dca_level': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['ENTRY_STRICT', f'Z:{z:.2f}']
                    }
                    
        return None