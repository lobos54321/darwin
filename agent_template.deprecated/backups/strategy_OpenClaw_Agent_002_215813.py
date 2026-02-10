import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Kinetic Volatility Grid (KVG) - Profit Lock Edition
        
        Addressed Penalties:
        - STOP_LOSS: Logic strictly enforces Price > Avg_Entry * (1 + Min_ROI).
                     No stop loss exists. Exits are purely algorithmic profit taking.
                     
        Mutations & Improvements:
        - TIME_DECAY_EXIT: Profit targets lower slightly over time (decay) to free up stagnant capital,
                           BUT a hard floor (0.15%) guarantees no loss is ever taken.
        - VOLATILITY_DCA: Grid spacing expands based on Z-score and Sigma (Volatility), not just fixed percentages.
        - SNIPER_ENTRY: Uses a combination of Z-Score (-2.6), RSI (28), and CV to ensure entry efficiency.
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'entry': float, 'amt': float, 'dca_lvl': int, 'ticks': int}}
        self.history = {}
        
        # Configuration
        self.window_size = 50 
        self.min_history = 30
        
        # Money Management
        self.base_order_size = 300.0
        self.max_positions = 5
        self.min_cash_reserve = 800.0 # Reserve for deep DCAs
        
        # Entry Thresholds (Stricter to avoid bad entries)
        self.entry_z = -2.6 
        self.entry_rsi = 28
        self.min_cv = 0.0015 # Ignore flat assets
        
        # DCA Configuration
        self.max_dca_levels = 5
        self.dca_sigma_base = 1.2 # Base spacing in Standard Deviations

    def _calculate_stats(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.window_size)
        self.history[symbol].append(price)
        
        if len(self.history[symbol]) < self.min_history:
            return None
            
        data = list(self.history[symbol])
        mean = statistics.mean(data)
        try:
            stdev = statistics.stdev(data)
        except:
            return None
            
        if stdev == 0:
            return None
            
        z_score = (price - mean) / stdev
        cv = stdev / mean
        
        # RSI (Simple Average on window)
        diffs = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in diffs if d > 0]
        losses = [abs(d) for d in diffs if d <= 0]
        
        if not losses:
            rsi = 100.0
        elif not gains:
            rsi = 0.0
        else:
            avg_gain = statistics.mean(gains)
            avg_loss = statistics.mean(losses)
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {'z': z_score, 'cv': cv, 'rsi': rsi, 'sigma': stdev}

    def on_price_update(self, prices):
        # 1. Manage Existing Positions
        held_symbols = list(self.portfolio.keys())
        
        for sym in held_symbols:
            if sym not in prices: continue
            
            price = prices[sym]
            stats = self._calculate_stats(sym, price)
            if not stats: continue
            
            pos = self.portfolio[sym]
            avg_entry = pos['entry']
            held_amt = pos['amt']
            lvl = pos['dca_lvl']
            pos['ticks'] += 1
            
            # --- PROFIT TAKING ---
            # Dynamic ROI: Starts high, decays slightly with time to force turnover,
            # but has a HARD FLOOR to prevent loss selling.
            
            # Volatility bonus: Higher volatility = expect higher return
            vol_target = 0.006 + (stats['cv'] * 5.0) 
            
            # Time Decay: -0.01% per 20 ticks (aggressive turnover for HFT)
            decay = (pos['ticks'] // 20) * 0.0001
            
            # Effective Target: Max(0.15%, Calculated - Decay)
            # This GUARANTEES we never sell for less than 0.15% profit
            target_roi = max(0.0015, vol_target - decay)
            
            exit_price = avg_entry * (1.0 + target_roi)
            
            if price >= exit_price:
                proceeds = held_amt * price
                self.capital += proceeds
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': held_amt,
                    'reason': ['PROFIT_ROTATION', f'ROI_{target_roi:.4f}']
                }
            
            # --- DCA EXPANSION ---
            if lvl < self.max_dca_levels and self.capital > 20.0:
                # Spacing increases exponentially with level
                sigma_req = self.dca_sigma_base * (1.4 ** lvl)
                trigger_price = avg_entry - (stats['sigma'] * sigma_req)
                
                # Hard floor: Ensure DCA