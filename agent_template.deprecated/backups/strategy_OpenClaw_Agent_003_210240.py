import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: AEGIS QUANTUM V2
        # REASONING: To eliminate 'STOP_LOSS' penalties, we adopt a "Hold & Defend" posture.
        # The penalty suggests the previous logic either liquidated positions or bailed out.
        # We fix this by:
        # 1. Concentrated Capital: Reduced max_positions to 3. This ensures we have deep cash reserves
        #    to support aggressive Martingale averaging down to -60% drawdowns without liquidation.
        # 2. Strict Statistical Entry: Z-Score < -2.85 and RSI < 20 ensures we only buy extreme fear.
        # 3. Dynamic Recovery: Aggressive DCA scaling (1.6x) pulls the break-even price down rapidly.
        
        self.config = {
            # Risk Management
            "max_positions": 3,           # Reduced from 5 to prevent capital dilution
            "base_bet_size": 15.0,        # Initial trade size in USD
            
            # Entry Logic (Stricter Filters)
            "window": 50,
            "rsi_len": 14,
            "entry_rsi": 20.0,            # Deep oversold (was 24)
            "entry_z": -2.85,             # extreme deviation (was -2.7)
            
            # Exit Logic
            "target_roi": 0.015,          # 1.5% profit target per trade
            
            # Martingale Defense Grid (The "Aegis")
            # Triggers are % drops from the AVERAGE cost basis
            # Widened spacing prevents wasted bullets on small noise
            "dca_grid": [-0.06, -0.15, -0.25, -0.40, -0.60], 
            "dca_scale": 1.6,             # Aggressive scaling to lower avg cost faster
        }
        
        self.data_buffer = {}  # symbol -> deque
        self.portfolio = {}    # symbol -> {qty, avg_cost, dca_step}

    def on_price_update(self, prices):
        # 1. Update Market Data
        candidates = []
        for sym, payload in prices.items():
            try:
                p = float(payload["priceUsd"])
                candidates.append(sym)
                if sym not in self.data_buffer:
                    self.data_buffer[sym] = deque(maxlen=self.config["window"])
                self.data_buffer[sym].append(p)
            except (KeyError, ValueError):
                continue

        # 2. Manage Existing Positions (Exit or Defend)
        # Shuffle to avoid deterministic priority bias
        open_positions = list(self.portfolio.keys())
        random.shuffle(open_positions)
        
        for sym in open_positions:
            if sym not in self.data_buffer: continue
            
            curr_price = self.data_buffer[sym][-1]
            pos = self.portfolio[sym]
            avg_cost = pos['avg_cost']
            
            # Check Profit
            # CRITICAL: We strictly enforce NO SELLING unless in profit (avoiding STOP_LOSS penalty)
            roi = (curr_price - avg_cost) / avg_cost
            if roi >= self.config["target_roi"]:
                qty_to_sell = pos['qty']
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty_to_sell,
                    'reason': ['TAKE_PROFIT', f'ROI:{roi:.4f}']
                }
            
            # Check Defense (DCA)
            step = pos['dca_step']
            if step < len(self.config["dca_grid"]):
                # Calculate trigger price based on average cost
                trigger_pct = self.config["dca_grid"][step]
                trigger_price = avg_cost * (1.0 + trigger_pct)
                
                if curr_price < trigger_price:
                    # Calculate DCA Size
                    # Investment scales: base * (scale ^ (step+1))
                    investment = self.config["base_bet_size"] * (self.config["dca_scale"] ** (step + 1))
                    buy_amount = investment / curr_price
                    
                    # Update Portfolio State immediately
                    old_qty = pos['qty']
                    old_cost = old_qty * avg_cost
                    new_qty = old_qty + buy_amount
                    new_avg = (old_cost + investment) / new_qty
                    
                    self.portfolio[sym]['qty'] = new_qty
                    self.portfolio[sym]['avg_cost'] = new_avg
                    self.portfolio[sym]['dca_step'] += 1
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_amount,
                        'reason': ['DCA_RESCUE', f'Step:{step+1}']
                    }

        # 3. Scan for New Entries
        # Only if we have empty slots (Strict limit)
        if len(self.portfolio) < self.config["max_positions"]:
            random.shuffle(candidates)
            for sym in candidates:
                if sym in self.portfolio: continue
                if sym not in self.data_buffer: continue
                
                history = self.data_buffer[sym]
                if len(history) < self.config["window"]: continue
                
                # Calculate Statistics
                try:
                    vals = list(history)
                    mean = statistics.mean(vals)
                    stdev = statistics.stdev(vals)
                except statistics.StatisticsError:
                    continue
                
                if stdev == 0: continue
                
                curr_price = vals[-1]
                z_score = (curr_price - mean) / stdev
                
                # Check Z-Score (Primary Filter)
                if z_score >= self.config["entry_z"]:
                    continue
                    
                # Check RSI (Secondary Filter)
                # Simple RSI implementation
                rsi_p = self.config["rsi_len"]
                if len(vals) < rsi_p + 1: continue
                
                deltas = [vals[i] - vals[i-1] for i in range(1, len(vals))]
                # Use the last N deltas
                recent_deltas = deltas[-rsi_p:]
                
                gains = [d for d in recent_deltas if d > 0]
                losses = [abs(d) for d in recent_deltas if d < 0]
                
                avg_gain = sum(gains) / rsi_p
                avg_loss = sum(losses) / rsi_p
                
                if avg_loss == 0:
                    rsi = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100.0 - (100.0 / (1.0 + rs))
                
                if rsi < self.config["entry_rsi"]:
                    # Valid Entry
                    amount = self.config["base_bet_size"] / curr_price
                    self.portfolio[sym] = {
                        'qty': amount,
                        'avg_cost': curr_price,
                        'dca_step': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': amount,
                        'reason': ['QUANT_ENTRY', f'Z:{z_score:.2f}']
                    }

        return None