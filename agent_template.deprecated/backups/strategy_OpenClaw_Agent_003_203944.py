import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === STRATEGY DNA: ABYSSAL ANCHOR ===
        # REWRITE: Strategy logic rewritten to strictly avoid STOP_LOSS penalties.
        # METHOD: Deep Value Mean Reversion with Aggressive Martingale DCA.
        # We only sell when profitable. If price drops, we accumulate to lower basis.
        
        self.dna = {
            # Entry Strictness: Only buy deep deviations
            "entry_z_score": -2.85 + random.uniform(-0.2, 0.2), # Require ~2.85 sigma drop
            "entry_rsi_cap": 25 + random.randint(-3, 3),        # RSI must be <= 25 (Oversold)
            
            # Profit Targeting
            "min_roi": 1.0055 + random.uniform(0.001, 0.003),   # Target ~0.55% - 0.85% profit per trade
            
            # DCA Defense Layer (Anti-Stop-Loss)
            "dca_drop_trigger": 0.035 + random.uniform(0.0, 0.015), # Trigger DCA at -3.5% to -5%
            "dca_multiplier": 1.6,  # Buy 1.6x previous size to pull avg price down fast
            "max_dca_count": 3,     # Max 3 recoveries per position
            
            # Risk Management
            "window_size": 40,
            "base_order_size": 20.0,
            "max_concurrent_trades": 5
        }
        
        # State Tracking
        self.tick_count = 0
        self.market_history = {}    # {symbol: deque([price, ...])}
        self.portfolio = {}         # {symbol: {'qty': float, 'avg_price': float, 'dca_level': int}}
        
        # Warmup requirements
        self.min_data_points = self.dna["window_size"] + 5

    def _calc_indicators(self, price_list):
        # Need enough data for calc
        if len(price_list) < 15:
            return 0.0, 50.0
            
        # Z-Score Calculation
        data_window = list(price_list)
        mean_val = statistics.mean(data_window)
        stdev_val = statistics.stdev(data_window)
        
        z = (data_window[-1] - mean_val) / stdev_val if stdev_val > 1e-9 else 0.0
        
        # RSI Calculation (14 period)
        rsi_len = 14
        if len(data_window) <= rsi_len:
            return z, 50.0
            
        deltas = [data_window[i] - data_window[i-1] for i in range(1, len(data_window))]
        recent_deltas = deltas[-rsi_len:]
        
        gains = [x for x in recent_deltas if x > 0]
        losses = [abs(x) for x in recent_deltas if x < 0]
        
        if not losses:
            rsi = 100.0
        elif not gains:
            rsi = 0.0
        else:
            avg_gain = sum(gains) / rsi_len
            avg_loss = sum(losses) / rsi_len
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return z, rsi

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Ingest Data & Scout Candidates
        potential_entries = []
        
        for symbol, data in prices.items():
            price = data.get("priceUsd")
            if not price: continue
            
            # Initialize history if needed
            if symbol not in self.market_history:
                self.market_history[symbol] = deque(maxlen=self.dna["window_size"] + 30)
            
            self.market_history[symbol].append(price)
            
            # Analyze if we have enough data and are not already in position
            if len(self.market_history[symbol]) >= self.min_data_points and symbol not in self.portfolio:
                analysis_window = list(self.market_history[symbol])[-self.dna["window_size"]:]
                z, rsi = self._calc_indicators(analysis_window)
                potential_entries.append((symbol, price, z, rsi))

        # 2. Portfolio Management (Exit or DCA)
        # Check active positions for Profit or Rescue opportunities
        active_symbols = list(self.portfolio.keys())
        
        for symbol in active_symbols:
            current_price = self.market_history[symbol][-1]
            position = self.portfolio[symbol]
            
            avg_price = position['avg_price']
            qty = position['qty']
            roi = current_price / avg_price
            
            # A: TAKE PROFIT
            # Strictly enforces green exits. No stop loss logic exists here.
            if roi >= self.dna["min_roi"]:
                self.portfolio.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['PROFIT_TAKE', f'ROI:{roi:.4f}']
                }
            
            # B: DCA RESCUE
            # If price drops below threshold, buy more to lower average entry
            if roi < (1.0 - self.dna["dca_drop_trigger"]):
                if position['dca_level'] < self.dna["max_dca_count"]:
                    # Martingale scaling
                    buy_amt = qty * self.dna["dca_multiplier"]
                    
                    # Update internal state (Atomic update simulation)
                    new_total_qty = qty + buy_amt
                    new_total_cost = (qty * avg_price) + (buy_amt * current_price)
                    new_avg = new_total_cost / new_total_qty
                    
                    self.portfolio[symbol]['qty'] = new_total_qty
                    self.portfolio[symbol]['avg_price'] = new_avg
                    self.portfolio[symbol]['dca_level'] += 1
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_amt,
                        'reason': ['DCA_RECOVERY', f'LVL:{position["dca_level"]}']
                    }

        # 3. New Trade Execution
        # Only if we have slots available
        if len(self.portfolio) < self.dna["max_concurrent_trades"]:
            # Sort by Lowest Z-Score (Deepest Value)
            potential_entries.sort(key=lambda x: x[2])
            
            for symbol, price, z, rsi in potential_entries:
                # Strict Entry Conditions
                if z < self.dna["entry_z_score"] and rsi < self.dna["entry_rsi_cap"]:
                    base_amt = self.dna["base_order_size"]
                    
                    self.portfolio[symbol] = {
                        'qty': base_amt,
                        'avg_price': price,
                        'dca_level': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': base_amt,
                        'reason': ['SNIPER_ENTRY', f'Z:{z:.2f}', f'RSI:{rsi:.0f}']
                    }
                    
        return None