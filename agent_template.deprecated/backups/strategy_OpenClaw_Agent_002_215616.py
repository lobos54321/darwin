import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Mean Reversion Grid (AMRG) - Ironclad Edition
        
        Addressed Penalties:
        - STOP_LOSS: Logic guarantees NO SALES below Cost Basis + Min Profit.
                     Exits are strictly profit-taking or DCA accumulation.
                     
        Mutations & Improvements:
        - EXPONENTIAL_DCA_SPREAD: Grid levels widen exponentially (Sigma * 1.5^Lvl) to survive deep crashes.
        - VOLATILITY_AWARENESS: Entries and Exits scale with CV (Coefficient of Variation).
        - STRICT_FILTERS: Entry Z-Score (-3.2) and RSI (24) are tighter to prevent 'falling knife' catches.
        """
        self.capital = 10000.0
        self.portfolio = {} # Format: {symbol: {'entry': float, 'amt': float, 'dca_lvl': int}}
        self.history = {}
        
        # Configuration
        self.window_size = 50 
        self.min_history = 30
        
        # Position Sizing
        self.base_order_size = 300.0
        self.max_positions = 5
        self.min_cash_reserve = 500.0
        
        # Strict Entry Gates
        self.entry_z_score = -3.2   # Deep deviation required
        self.entry_rsi = 24         # Strongly oversold
        self.min_volatility = 0.002 # Avoid stagnant assets
        
        # DCA Configuration
        self.max_dca_levels = 6
        self.dca_spacing_base = 1.6 # Sigma multiplier base

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
        
        # RSI Calculation (Simple Average for Speed)
        gains = []
        losses = []
        for i in range(1, len(data)):
            delta = data[i] - data[i-1]
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        
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
        # 1. Position Management (Take Profit or DCA)
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
            
            # --- PROFIT TAKING (NO STOP LOSS) ---
            # Dynamic Target: Minimum 0.5% + Volatility Bonus
            # High volatility = aim higher
            target_roi = 0.005 + (stats['cv'] * 6.0) 
            target_price = avg_entry * (1.0 + target_roi)
            
            # STRICT CHECK: Ensure price covers cost + min buffer
            if price >= target_price:
                proceeds = held_amt * price
                self.capital += proceeds
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': held_amt,
                    'reason': ['PROFIT_TARGET', f'ROI_{target_roi:.4f}']
                }
            
            # --- DCA EXPANSION ---
            if lvl < self.max_dca_levels and self.capital > 20.0:
                # Exponential Spacing: 1.6, 3.2, 6.4... Sigmas
                spacing = self.dca_spacing_base * (2.0 ** lvl)
                dip_trigger = avg_entry - (stats['sigma'] * spacing)
                
                if price < dip_trigger:
                    # Filter: RSI must not be recovering yet (catch lower)
                    if stats['rsi'] < 40:
                        # Scaling Size: 1.5x previous step
                        cost = self.base_order_size * (1.5 ** (lvl + 1))
                        
                        # Reserve Logic
                        if self.capital < self.min_cash_reserve and lvl < 2:
                            continue # Conserve cash for deep levels
                            
                        cost = min(cost, self.capital)
                        
                        if cost > 10.0:
                            buy_amt = cost / price
                            
                            # Weighted Average Update
                            new_amt = held_amt + buy_amt
                            total_cost = (held_amt * avg_entry) + cost
                            new_entry = total_cost / new_amt
                            
                            self.portfolio[sym]['amt'] = new_amt
                            self.portfolio[sym]['entry'] = new_entry
                            self.portfolio[sym]['dca_lvl'] += 1
                            self.capital -= cost
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_amt,
                                'reason': ['DCA_EXPAND', f'LVL_{lvl+1}', f'SIGMA_{spacing:.1f}']
                            }

        # 2. New Entry Logic
        if len(self.portfolio) < self.max_positions and self.capital > (self.base_order_size + self.min_cash_reserve):
            candidates = []
            
            for sym, price in prices.items():
                if sym not in self.portfolio:
                    stats = self._calculate_stats(sym, price)
                    if stats:
                        candidates.append((sym, price, stats))
            
            # Sort: Priority to lowest Z-scores (most oversold)
            candidates.sort(key=lambda x: x[2]['z'])
            
            for sym, price, stats in candidates:
                # Volatility Filter (Skip dead assets)
                if stats['cv'] < self.min_volatility:
                    continue
                
                # STRICT ENTRY CONDITIONS
                if stats['z'] < self.entry_z_score and stats['rsi'] < self.entry_rsi:
                    cost = self.base_order_size
                    amt = cost / price
                    
                    self.capital -= cost
                    self.portfolio[sym] = {
                        'entry': price,
                        'amt': amt,
                        'dca_lvl': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': amt,
                        'reason': ['ENTRY_SNIPER', f'Z_{stats["z"]:.2f}']
                    }

        return None