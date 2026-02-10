import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Sigma-Adaptive Mean Reversion (SAMR)
        
        Fixes & Mutations:
        1. NO_STOP_LOSS_GUARANTEE: Logic explicitly filters sell orders to ensure (Price > Avg_Entry * 1.0025).
           The 0.25% buffer accounts for potential slippage/fees to ensure net profitability.
        2. SIGMA_DCA_GRID: Instead of arbitrary percentages, DCA levels are spaced by standard deviations (Sigma).
           This adapts the 'net' to the specific asset's volatility. High vol = wider nets.
        3. STRICT_REGIME_FILTER: Entry requires Z-Score < -2.8 and RSI < 30.
           Added a 'Volatility Gate': If CV is too low, we don't enter (avoid value traps).
        """
        self.capital = 10000.0
        self.portfolio = {}  # {symbol: {'amt': float, 'entry': float, 'dca_lvl': int, 'sigma_at_entry': float}}
        self.history = {}
        
        # Configuration
        self.window_size = 50
        self.base_order_size = 200.0
        self.max_positions = 5
        self.min_cash_reserve = 1500.0
        
        # Entry Thresholds (Stricter to satisfy Dip Buy penalty risk)
        self.entry_z_score = -2.8
        self.entry_rsi = 30
        self.min_volatility_cv = 0.002 # Avoid dead assets
        
        # Dynamic DCA Settings
        self.max_dca_levels = 6
        # Multipliers for Sigma to determine drop distance: 1sigma, 2sigma, 3sigma...
        self.dca_sigma_multipliers = [1.5, 2.5, 4.0, 6.0, 9.0, 13.0]

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
        cv = stdev / mean
        
        # RSI Calculation
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
                
        return {'z': z_score, 'cv': cv, 'rsi': rsi, 'stdev': stdev, 'mean': mean}

    def on_price_update(self, prices):
        # --- 1. Position Management (Exits & DCA) ---
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
            
            # Retrieve the volatility (sigma) at time of entry/last update if possible, 
            # else use current. Using current scales with recent market chaos.
            sigma = stats['stdev']
            
            # --- EXIT LOGIC (STRICT NO LOSS) ---
            # Minimum strict ROI to cover potential fees/slippage
            min_roi = 0.0025 
            # Dynamic target based on volatility
            dynamic_roi = 0.01 + (stats['cv'] * 5.0)
            target_roi = max(min_roi, dynamic_roi)
            
            target_price = avg_entry * (1.0 + target_roi)
            
            # CRITICAL: STOP LOSS PENALTY PREVENTION
            # We strictly check if price > avg_entry * (1 + buffer)
            if price >= target_price and price > (avg_entry * (1.0 + min_roi)):
                proceeds = held_amt * price
                self.capital += proceeds
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': held_amt,
                    'reason': ['PROFIT_TAKE', f'ROI_{target_roi:.4f}']
                }
            
            # --- DCA LOGIC (SIGMA ADAPTIVE) ---
            if lvl < len(self.dca_sigma_multipliers) and self.capital > 10.0:
                # Calculate required drop based on Sigma Multiplier
                # We need the price to be below: Entry - (Multiplier * Sigma)
                sigma_mult = self.dca_sigma_multipliers[lvl]
                # Use a blend of Entry price and moving average to determine "dip"
                # Using Entry as anchor ensures we space out orders relative to our bad position
                required_price = avg_entry - (sigma * sigma_mult)
                
                if price < required_price:
                    # Filter: Don't buy if RSI is still screaming high (falling knife check)
                    # Relaxed RSI for DCA compared to Entry, but still present
                    if stats['rsi'] < 45:
                        # Position Sizing: Linear scaling
                        size_multiplier = 1.0 + (lvl * 0.5)
                        cost = self.base_order_size * size_multiplier
                        
                        # Reserve Logic
                        if self.capital < self.min_cash_reserve and lvl < 3:
                            continue # Hold reserve for deep distress (lvl 3+)
                            
                        cost = min(cost, self.capital)
                        
                        if cost > 5.0:
                            buy_amt = cost / price
                            
                            # Update Weighted Average
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
                                'reason': ['DCA_SIGMA', f'LVL_{lvl+1}', f'SIGMA_{sigma_mult}']
                            }

        # --- 2. New Entry Logic ---
        if len(self.portfolio) < self.max_positions and self.capital > (self.base_order_size + self.min_cash_reserve):
            candidates = []
            
            for sym, price in prices.items():
                if sym not in self.portfolio:
                    stats = self._calculate_stats(sym, price)
                    if stats:
                        candidates.append((sym, price, stats))
            
            # Sort by Z-score (lowest first)
            candidates.sort(key=lambda x: x[2]['z'])
            
            for sym, price, stats in candidates:
                # Filter 1: Minimum Volatility (Don't trade flat lines)
                if stats['cv'] < self.min_volatility_cv:
                    continue
                    
                # Filter 2: Strict Z-Score & RSI
                # We dynamically adjust Z req based on RSI. Lower RSI allows slightly higher Z.
                # Base Requirement
                valid_entry = False
                
                if stats['z'] < self.entry_z_score and stats['rsi'] < self.entry_rsi:
                    valid_entry = True
                
                # 'Super Dip' Override: If RSI is extremely low (<15), relax Z-score slightly
                if stats['rsi'] < 15 and stats['z'] < (self.entry_z_score + 0.5):
                    valid_entry = True
                    
                if valid_entry:
                    cost = self.base_order_size
                    amt = cost / price
                    
                    self.capital -= cost
                    self.portfolio[sym] = {
                        'entry': price,
                        'amt': amt,
                        'dca_lvl': 0,
                        'sigma_at_entry': stats['stdev']
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': amt,
                        'reason': ['ENTRY_SIGMA', f'Z_{stats["z"]:.2f}', f'RSI_{stats["rsi"]:.1f}']
                    }
                    
        return None