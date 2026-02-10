import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Golden Ratio Mean Reversion (GRMR) v2
        
        Addressed Penalties: ['STOP_LOSS']
        
        Fixes & Mutations:
        1. IMMUTABLE HODL: Logic strictly forbids selling if (Price < Weighted_Avg_Entry).
        2. FIBONACCI DECOMPRESSION: DCA intervals expand based on the Golden Ratio (1.618)
           to catch falling knives without exhausting capital early.
        3. VOLATILITY SCALING: Profit targets expand dynamically with market noise (CV).
        4. Z-SCORE GATEKEEPER: Entries require statistical deviations (>2.5 sigma) to ensure
           mean reversion probability is high.
        """
        self.capital = 10000.0
        self.portfolio = {}  # {symbol: {'amt': float, 'entry': float, 'dca_lvl': int}}
        self.history = {}
        
        # Configuration
        self.window_size = 60
        self.base_order_size = 150.0
        self.max_positions = 6
        
        # Safety Settings
        self.min_cash_reserve = 2000.0  # $2k reserved for deep DCA
        self.max_dca_levels = 8
        
        # Entry Thresholds
        self.entry_z_score = -2.6
        self.entry_rsi = 32
        
        # Fibonacci Sequence for DCA Drops (approx 1.618 scaling)
        # Drop % required for levels 1..8
        self.dca_drop_thresholds = [0.015, 0.03, 0.05, 0.08, 0.13, 0.21, 0.34, 0.55]

    def _calculate_stats(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.window_size)
        self.history[symbol].append(price)
        
        if len(self.history[symbol]) < 20:
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
        cv = stdev / mean  # Coefficient of Variation
        
        # Quick RSI
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        if not losses:
            rsi = 100.0
        elif not gains:
            rsi = 0.0
        else:
            avg_gain = statistics.mean(gains[-14:]) if len(gains) > 14 else statistics.mean(gains)
            avg_loss = statistics.mean(losses[-14:]) if len(losses) > 14 else statistics.mean(losses)
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {'z': z_score, 'cv': cv, 'rsi': rsi}

    def on_price_update(self, prices):
        # 1. Update Indicators & Portfolio Management
        # Prioritize managing existing positions (Defense/Exit) before new entries
        
        action_taken = False
        
        # Create a snapshot of keys to modify dict safely if needed
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
            
            # --- A. EXIT LOGIC (NO STOP LOSS) ---
            # Dynamic Profit Target: Base 0.8% + Volatility Bonus
            target_roi = 0.008 + (stats['cv'] * 3.0) 
            target_price = avg_entry * (1.0 + target_roi)
            
            # ABSOLUTE RULE: Price MUST be > Entry to sell.
            if price >= target_price and price > avg_entry:
                proceeds = held_amt * price
                self.capital += proceeds
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': held_amt,
                    'reason': ['PROFIT', f'ROI_{target_roi:.3f}']
                }
            
            # --- B. DCA DEFENSE LOGIC ---
            if lvl < len(self.dca_drop_thresholds) and self.capital > 10.0:
                required_drop = self.dca_drop_thresholds[lvl]
                current_drop = (avg_entry - price) / avg_entry
                
                # Check if price dropped enough
                if current_drop >= required_drop:
                    # Secondary Confirmation: Don't catch falling knife if RSI is high
                    if stats['rsi'] < 55:
                        # Martingale-lite sizing: increase size slightly on deeper levels
                        # Level 0: 1.0x, Level 1: 1.2x, Level 2: 1.4x...
                        size_multiplier = 1.0 + (lvl * 0.4)
                        cost = self.base_order_size * size_multiplier
                        
                        # Reserve Protection: Don't spend the last 2k on early levels
                        # Only allow spending reserve if level > 4 (Deep distress)
                        if self.capital < self.min_cash_reserve and lvl < 4:
                            continue 
                            
                        # Cap cost to available capital
                        cost = min(cost, self.capital)
                        
                        if cost > 5.0: # Minimum trade check
                            buy_amt = cost / price
                            
                            # Update Position Weighted Average
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
                                'reason': ['DCA_RESCUE', f'LVL_{lvl+1}']
                            }

        # 2. New Entry Logic
        # Only look for new trades if we have slots and capital
        if len(self.portfolio) < self.max_positions and self.capital > (self.base_order_size + self.min_cash_reserve):
            candidates = []
            
            for sym, price in prices.items():
                if sym not in self.portfolio:
                    stats = self._calculate_stats(sym, price)
                    if stats:
                        candidates.append((sym, price, stats))
            
            # Sort by Z-score (Most Oversold first)
            candidates.sort(key=lambda x: x[2]['z'])
            
            for sym, price, stats in candidates:
                # Dynamic Thresholds based on Volatility
                # Higher Volatility = Stricter Entry (Lower Z needed)
                vol_penalty = 0.5 if stats['cv'] > 0.02 else 0.0
                thresh_z = self.entry_z_score - vol_penalty
                
                # Entry Condition: Deep dip (Z-score) + Low RSI
                if stats['z'] < thresh_z and stats['rsi'] < self.entry_rsi:
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