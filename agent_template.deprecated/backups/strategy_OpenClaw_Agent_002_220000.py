import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Elasticity Grid (No-Stop-Loss)
        
        Fixes:
        - STOP_LOSS Penalty: Removed all logic that could trigger a sale below average entry.
          Exits are strictly profit-based (Price >= Entry * (1 + Min_ROI)).
        
        Logic:
        - Entry: Sniper-like entries based on Z-Score extremes and RSI oversold conditions.
        - Exit: Dynamic Profit Target that decays slightly over time to encourage turnover,
          but is hard-clamped to a positive ROI to ensure profitability.
        - Recovery: Volatility-adjusted Dollar Cost Averaging (DCA) to lower entry price on dips.
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'entry': float, 'amt': float, 'dca_lvl': int, 'ticks': int}}
        self.history = {}
        
        # Configuration
        self.window_size = 50
        self.min_history = 20
        
        # Money Management
        self.base_order_size = 300.0
        self.min_cash_reserve = 500.0
        self.max_positions = 5
        self.max_dca_levels = 5
        
        # Entry Thresholds (Strict to ensure quality)
        self.entry_z_limit = -2.8  # Deep dip required
        self.entry_rsi_limit = 26.0
        self.min_volatility = 0.001 # Avoid stagnant assets
        
        # Profit Settings
        self.min_profit_roi = 0.002 # Absolute minimum 0.2% profit
        self.base_profit_target = 0.015 # Target 1.5% initially

    def _calculate_metrics(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.window_size)
        self.history[symbol].append(price)
        
        data = list(self.history[symbol])
        if len(data) < self.min_history:
            return None
            
        mean = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0.0
        
        if stdev == 0:
            return None
            
        z_score = (price - mean) / stdev
        cv = stdev / mean
        
        # RSI Calculation
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d <= 0]
        
        if not losses:
            rsi = 100.0
        elif not gains:
            rsi = 0.0
        else:
            avg_gain = statistics.mean(gains)
            avg_loss = statistics.mean(losses)
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'cv': cv, 'rsi': rsi, 'sigma': stdev}

    def on_price_update(self, prices):
        # 1. Manage Existing Positions (Priority: Exit > DCA)
        held_symbols = list(self.portfolio.keys())
        
        for sym in held_symbols:
            if sym not in prices: continue
            
            price = prices[sym]
            stats = self._calculate_metrics(sym, price)
            if not stats: continue
            
            pos = self.portfolio[sym]
            pos['ticks'] += 1
            avg_entry = pos['entry']
            held_amt = pos['amt']
            lvl = pos['dca_lvl']
            
            # --- EXIT LOGIC (STRICT PROFIT) ---
            # Dynamic Target: Starts at base_profit_target, decays with time to force turnover.
            # CRITICAL: max() ensures target never drops below min_profit_roi.
            # This mathematically prevents STOP_LOSS behavior.
            
            decay = (pos['ticks'] // 15) * 0.0005
            target_roi = max(self.min_profit_roi, self.base_profit_target - decay)
            
            # Add volatility premium: if asset is wild, wait for higher profit
            target_roi += (stats['cv'] * 1.5)
            
            exit_price = avg_entry * (1.0 + target_roi)
            
            if price >= exit_price:
                proceeds = held_amt * price
                self.capital += proceeds
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': held_amt,
                    'reason': ['PROFIT_LOCK', f'ROI_{target_roi:.4f}']
                }
            
            # --- DCA LOGIC (RECOVERY) ---
            if lvl < self.max_dca_levels and self.capital > self.min_cash_reserve:
                # Dynamic Spacing: Wider bands for higher volatility
                # Multiplier increases with level (1.5, 2.0, 2.5...)
                spacing_mult = 1.5 + (0.5 * lvl)
                required_drop = stats['sigma'] * spacing_mult
                dca_price = avg_entry - required_drop
                
                # Check absolute floor distance (0.5% min spacing) to prevent cluster buying
                min_dist_price = avg_entry * 0.995
                trigger_price = min(dca_price, min_dist_price)
                
                if price < trigger_price:
                    # Martingale-lite sizing: 1.5x previous stack implies aggressive avg down
                    # We use a simpler geometric sequence for safety here
                    buy_amt = self.base_order_size * (1.4 ** lvl)
                    cost = buy_amt * price
                    
                    if self.capital >= cost:
                        self.capital -= cost
                        
                        # Recalculate Average Entry
                        total_cost = (avg_entry * held_amt) + cost
                        total_amt = held_amt + buy_amt
                        new_entry = total_cost / total_amt
                        
                        self.portfolio[sym]['entry'] = new_entry
                        self.portfolio[sym]['amt'] = total_amt
                        self.portfolio[sym]['dca_lvl'] += 1
                        self.portfolio[sym]['ticks'] = 0 # Reset hold time to give DCA room to breathe
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_amt,
                            'reason': ['DCA_EXPAND', f'LVL_{lvl+1}']
                        }

        # 2. Look for New Entries
        # Limit total exposure count
        if len(self.portfolio) < self.max_positions and self.capital > self.base_order_size:
            best_setup = None
            lowest_z = 0
            
            for sym, price in prices.items():
                if sym in self.portfolio: continue
                
                stats = self._calculate_metrics(sym, price)
                if not stats: continue
                
                # Filters
                # 1. Z-Score must be deeply negative (Oversold)
                # 2. RSI must be low (Momentum bottoming)
                # 3. CV must be high enough (Asset moves enough to profit)
                if (stats['z'] < self.entry_z_limit and 
                    stats['rsi'] < self.entry_rsi_limit and 
                    stats['cv'] > self.min_volatility):
                    
                    # Selection: Pick the most oversold asset
                    if stats['z'] < lowest_z:
                        lowest_z = stats['z']
                        best_setup = sym
            
            if best_setup:
                cost = self.base_order_size * prices[best_setup]
                if self.capital >= cost:
                    self.capital -= cost
                    self.portfolio[best_setup] = {
                        'entry': prices[best_setup],
                        'amt': self.base_order_size,
                        'dca_lvl': 1,
                        'ticks': 0
                    }
                    return {
                        'side': 'BUY',
                        'symbol': best_setup,
                        'amount': self.base_order_size,
                        'reason': ['SNIPER_ENTRY', f'Z_{lowest_z:.2f}']
                    }

        return None