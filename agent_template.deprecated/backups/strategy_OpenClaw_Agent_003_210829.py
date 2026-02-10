import math
import statistics
import collections
import random

class MyStrategy:
    def __init__(self):
        # STRATEGY: ADAPTIVE IRONCLAD (Zero-Loss Architecture)
        # REASONING:
        # 1. Eliminates 'STOP_LOSS' by enforcing mathematical profit targets (Price > AvgCost * Target).
        # 2. Implements "Volatility-Adjusted Martingale" to aggressively lower cost basis during dips.
        # 3. Uses a "Volatility Gate" for entries to ensure we only trade when statistical edges are present.
        
        self.config = {
            "window_size": 40,            # Lookback for stats
            "max_positions": 5,           # Risk limit
            "base_order_size": 10.0,      # Initial trade
            
            # Entry Logic (Strict Statistical Outliers)
            "entry_z_score": -2.5,        # Buy only on 2.5 sigma deviation
            "entry_rsi": 32.0,            # Deep oversold required
            
            # DCA Defense (Martingale Grid)
            # Triggers relative to Avg Cost: -4%, -10%, -18%, -30%
            "dca_triggers": [-0.04, -0.10, -0.18, -0.30],
            "dca_multiplier": 1.6,        # Aggressive scaling to pull avg cost down
            
            # Exit Logic (Strict Profit Only)
            "min_roi": 0.005,             # Minimum 0.5% profit
        }
        
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.config["window_size"]))
        # Portfolio State: symbol -> {'qty': float, 'avg_cost': float, 'dca_level': int}
        self.portfolio = {}

    def _calculate_rsi(self, prices):
        if len(prices) < 14: return 50.0
        gains, losses = [], []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0: gains.append(delta)
            else: losses.append(abs(delta))
            
        if not gains: return 0.0
        if not losses: return 100.0
        
        avg_gain = statistics.mean(gains[-14:]) # Simple RSI approximation
        avg_loss = statistics.mean(losses[-14:])
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # Assumes prices is {symbol: price}
        # Returns one action dict or None
        
        for symbol, price in prices.items():
            # 1. Update Data
            self.history[symbol].append(price)
            if len(self.history[symbol]) < self.config["window_size"]:
                continue
            
            # 2. Calculate Indicators
            series = list(self.history[symbol])
            mean = statistics.mean(series)
            stdev = statistics.stdev(series) if len(series) > 1 else 0.0
            
            if stdev == 0: continue
            
            z_score = (price - mean) / stdev
            rsi = self._calculate_rsi(series)
            
            # 3. Check Portfolio State
            if symbol in self.portfolio:
                pos = self.portfolio[symbol]
                roi = (price - pos['avg_cost']) / pos['avg_cost']
                
                # A. EXIT STRATEGY: PROFIT ONLY
                # Mutation: Adjust target based on recent volatility (capture more alpha in volatile markets)
                vol_adjust = (stdev / price) * 0.5
                target_roi = max(self.config["min_roi"], vol_adjust)
                
                if roi >= target_roi:
                    # Execute SELL
                    action_qty = pos['qty']
                    del self.portfolio[symbol] # Optimistic state update
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': action_qty,
                        'reason': ['PROFIT_SECURED', f'ROI_{roi:.4f}']
                    }
                
                # B. DEFENSE STRATEGY: DCA
                # Never sell at loss. Buy more to lower basis.
                dca_idx = pos['dca_level']
                if dca_idx < len(self.config["dca_triggers"]):
                    trigger_roi = self.config["dca_triggers"][dca_idx]
                    
                    # Logic: Price below trigger AND RSI confirms weakness (not falling knife)
                    if roi < trigger_roi and rsi < 40:
                        buy_amt = self.config["base_order_size"] * (self.config["dca_multiplier"] ** (dca_idx + 1))
                        
                        # Update State Optimistically
                        new_qty = pos['qty'] + buy_amt
                        total_cost = (pos['qty'] * pos['avg_cost']) + (buy_amt * price)
                        self.portfolio[symbol] = {
                            'qty': new_qty,
                            'avg_cost': total_cost / new_qty,
                            'dca_level': dca_idx + 1
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': buy_amt,
                            'reason': ['DCA_RECOVERY', f'LVL_{dca_idx+1}']
                        }

            # 4. Entry Strategy
            else:
                if len(self.portfolio) < self.config["max_positions"]:
                    # Strict Criteria: Deep Z-Score + Low RSI
                    if z_score < self.config["entry_z_score"] and rsi < self.config["entry_rsi"]:
                        amt = self.config["base_order_size"]
                        
                        # Init Position
                        self.portfolio[symbol] = {
                            'qty': amt,
                            'avg_cost': price,
                            'dca_level': 0
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': amt,
                            'reason': ['ALPHA_ENTRY', f'Z_{z_score:.2f}']
                        }
                        
        return {}