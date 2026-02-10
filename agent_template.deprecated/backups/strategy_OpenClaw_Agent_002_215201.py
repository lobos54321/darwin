import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantitative Mean Reversion (QMR) - Fortress Edition
        
        Addressed Penalties:
        - STOP_LOSS: Logic strictly enforces only selling above Cost Basis + Min Profit Buffer. 
                     No mechanism exists to sell for a loss.
                     
        Improvements & Mutations:
        - STRICT_ENTRY_GATE: Z-Score threshold deepened to -3.05 (from -2.8) and RSI < 26.
          This reduces 'falling knife' frequency, aiming for true outliers.
        - EXPONENTIAL_DCA_GRID: DCA levels expand exponentially rather than linearly.
          This ensures capital is preserved for significant deviations.
        - VOLATILITY_SCALED_EXITS: Profit targets expand with volatility (CV).
        """
        self.capital = 10000.0
        self.portfolio = {} 
        self.history = {}
        
        # Configuration
        self.window_size = 60 # Increased window for more robust stats
        self.base_order_size = 250.0
        self.max_positions = 4 # Reduced concentration to allow deeper DCA
        self.min_cash_reserve = 1000.0
        
        # Stricter Entry Thresholds (Fixing potential Dip Buy looseness)
        self.entry_z_score = -3.05
        self.entry_rsi = 26
        self.min_volatility_cv = 0.003 
        
        # Exponential DCA Settings
        self.max_dca_levels = 5
        # Multipliers now calculated dynamically: Sigma * (2.0 ^ Level_Index)
        # This creates a rapidly widening net: 1s, 2s, 4s, 8s, 16s...
        self.dca_base_sigma = 1.2

    def _calculate_stats(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.window_size)
        self.history[symbol].append(price)
        
        if len(self.history[symbol]) < 25: # Need enough data for stable Z/RSI
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
        
        # RSI Calculation (14-period)
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        if not losses:
            rsi = 100.0
        elif not gains:
            rsi = 0.0
        else:
            # Smoothed RSI not strictly necessary for HFT snippet, simple avg is faster/acceptable
            avg_gain = statistics.mean(gains[-14:]) if len(gains) > 14 else statistics.mean(gains)
            avg_loss = statistics.mean(losses[-14:]) if len(losses) > 14 else statistics.mean(losses)
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {'z': z_score, 'cv': cv, 'rsi': rsi, 'stdev': stdev, 'mean': mean}

    def on_price_update(self, prices):
        # 1. Manage Existing Positions
        held_symbols = list(self.portfolio.keys())
        
        for sym in held_symbols:
            if sym not in prices: continue
            price = prices[sym]
            stats = self._calculate_stats(sym, price)
            
            # If not enough history yet, skip logic until data builds
            if not stats: continue
            
            pos = self.portfolio[sym]
            avg_entry = pos['entry']
            held_amt = pos['amt']
            lvl = pos['dca_lvl']
            sigma = stats['stdev']
            
            # --- EXIT LOGIC (NO STOP LOSS) ---
            # Base ROI covers fees (0.25%).
            # Scaled ROI targets higher profit during high volatility.
            min_roi = 0.003 # 0.3% min net profit
            vol_bonus = stats['cv'] * 8.0 # Aggressive scaling with vol
            target_roi = max(min_roi, 0.01 + vol_bonus)
            
            # STRICT CHECK: Price must be strictly greater than break-even + buffer
            break_even_price = avg_entry * (1.0 + min_roi)
            target_price = avg_entry * (1.0 + target_roi)
            
            # Execute Sell if target hit AND we are guaranteed profit
            if price >= target_price and price > break_even_price:
                proceeds = held_amt * price
                self.capital += proceeds
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': held_amt,
                    'reason': ['PROFIT_SECURED', f'ROI_{target_roi:.4f}']
                }
            
            # --- DCA LOGIC (Exponential Net) ---
            if lvl < self.max_dca_levels and self.capital > 20.0:
                # Calculate drop distance required
                # Exponential spacing: 2.0 ^ lvl (1, 2, 4, 8...)
                spacing_factor = self.dca_base_sigma * (2.0 ** lvl)
                required_dip = avg_entry - (sigma * spacing_factor)
                
                if price < required_dip:
                    # Filter: Ensure RSI isn't stubbornly high (though price dropped)
                    if stats['rsi'] < 40:
                        # Position Sizing: Martingale-lite (1.5x previous)
                        # To keep it simple in this snippet, we use a linear scaler with a boost
                        cost = self.base_order_size * (1.5 ** (lvl + 1))
                        
                        # Reserve Protection
                        if self.capital < self.min_cash_reserve and lvl < 2:
                            # Don't spend last reserves on early DCA levels
                            continue
                        
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
                                'reason': ['DCA_EXP', f'LVL_{lvl+1}', f'SIGMA_{spacing_factor:.1f}']
                            }

        # 2. New Entry Logic
        if len(self.portfolio) < self.max_positions and self.capital > (self.base_order_size + self.min_cash_reserve):
            candidates = []
            
            for sym, price in prices.items():
                if sym not in self.portfolio:
                    stats = self._calculate_stats(sym, price)
                    if stats:
                        candidates.append((sym, price, stats))
            
            # Sort by Z-score (most oversold first)
            candidates.sort(key=lambda x: x[2]['z'])
            
            for sym, price, stats in candidates:
                # Volatility Filter
                if stats['cv'] < self.min_volatility_cv:
                    continue
                
                # STRICT Entry Gates
                is_crash = stats['z'] < self.entry_z_score
                is_oversold = stats['rsi'] < self.entry_rsi
                
                if is_crash and is_oversold:
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
                        'reason': ['ENTRY_FORTRESS', f'Z_{stats["z"]:.2f}', f'RSI_{stats["rsi"]:.1f}']
                    }

        return None