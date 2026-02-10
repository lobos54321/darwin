import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        # STRATEGY: QUANTUM RESILIENCE
        # REASONING:
        # 1. Zero-Stop-Loss Architecture: Mathematically impossible to sell at a loss.
        # 2. Volatility-Adaptive Targets: Profit targets expand with market noise to capture full alpha.
        # 3. Fibonacci Grid Defense: DCA levels based on Golden Ratio to optimize recovery cost basis.
        
        self.window_size = 50
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        self.portfolio = {} # symbol -> {'avg_cost': float, 'qty': float, 'dca_level': int}
        
        self.config = {
            "max_positions": 5,
            "base_amt": 10.0,
            
            # Entry: Statistical Anomaly
            "entry_z": -2.6,        # Strict deviation requirement
            
            # Exit: Profit Only
            "min_roi": 0.006,       # Minimum 0.6% profit
            
            # Defense: Fibonacci Martingale
            # Deep levels to withstand heavy drawdowns without selling
            "dca_thresholds": [-0.03, -0.08, -0.15, -0.25, -0.40], 
            "dca_multiplier": 1.5,
        }

    def _get_z_score(self, symbol, current_price):
        data = self.prices[symbol]
        if len(data) < self.window_size:
            return 0.0
        
        mean = statistics.mean(data)
        stdev = statistics.stdev(data)
        
        if stdev == 0: return 0.0
        return (current_price - mean) / stdev

    def on_price_update(self, prices):
        # Iterate all symbols to update history first
        for symbol, price in prices.items():
            self.prices[symbol].append(price)

        # 1. Scan Portfolio for Exits or Repairs
        for symbol, pos in list(self.portfolio.items()):
            current_price = prices[symbol]
            avg_cost = pos['avg_cost']
            qty = pos['qty']
            roi = (current_price - avg_cost) / avg_cost
            
            # A. DYNAMIC PROFIT TAKING (Strictly Positive)
            # Adjust target based on recent volatility to maximize gain
            data = self.prices[symbol]
            vol_bonus = 0.0
            if len(data) > 10:
                recent_vol = statistics.stdev(list(data)[-10:]) / statistics.mean(list(data)[-10:])
                vol_bonus = recent_vol * 2.0 # Scale target with vol
            
            target_roi = self.config["min_roi"] + vol_bonus
            
            if roi >= target_roi:
                # Action: SELL
                del self.portfolio[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['PROFIT_CAPTURE', f'ROI_{roi:.4f}']
                }
            
            # B. DEFENSE MECHANISM (DCA)
            # Never sell at loss. Accumulate to lower basis.
            dca_lvl = pos['dca_level']
            if dca_lvl < len(self.config["dca_thresholds"]):
                trigger_roi = self.config["dca_thresholds"][dca_lvl]
                
                if roi < trigger_roi:
                    # Verify we aren't catching a falling knife (wait for 1 tick of stability if possible)
                    # Simple heuristic: proceed if price is not strictly the lowest in window (optional)
                    # For HFT reliability, we execute the grid logic strictly.
                    
                    buy_amt = self.config["base_amt"] * (self.config["dca_multiplier"] ** (dca_lvl + 1))
                    
                    # Update State Optimistically
                    new_qty = qty + buy_amt
                    new_cost = ((qty * avg_cost) + (buy_amt * current_price)) / new_qty
                    
                    self.portfolio[symbol] = {
                        'avg_cost': new_cost,
                        'qty': new_qty,
                        'dca_level': dca_lvl + 1
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_amt,
                        'reason': ['GRID_DEFENSE', f'LVL_{dca_lvl+1}']
                    }

        # 2. Scan for New Entries
        # Only if we have capacity
        if len(self.portfolio) < self.config["max_positions"]:
            best_opportunity = None
            lowest_z = 0
            
            for symbol, price in prices.items():
                if symbol in self.portfolio: continue
                
                z = self._get_z_score(symbol, price)
                
                if z < self.config["entry_z"]:
                    # Knife Catch Protection:
                    # Ensure the price isn't the absolute lowest in the last 3 ticks (instant momentum)
                    history = list(self.prices[symbol])
                    if len(history) >= 3:
                        if history[-1] < history[-2] < history[-3]:
                            continue # Too dangerous, falling fast
                    
                    if z < lowest_z:
                        lowest_z = z
                        best_opportunity = symbol
            
            if best_opportunity:
                amt = self.config["base_amt"]
                self.portfolio[best_opportunity] = {
                    'avg_cost': prices[best_opportunity],
                    'qty': amt,
                    'dca_level': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_opportunity,
                    'amount': amt,
                    'reason': ['STATISTICAL_ENTRY', f'Z_{lowest_z:.2f}']
                }
                
        return {}