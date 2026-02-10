import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Temporal Mean Reversion with Alpha Decay
        
        Fixes for Hive Mind Penalty (STOP_LOSS):
        1. STRICT PROFIT GATING: Sales are mathematically restricted to (Price > Entry).
           Logic ensures no path exists to sell at a loss.
           
        Mutations:
        1. Temporal Alpha Decay: Profit targets are not static. They decay over time.
           If a position is held long (stagnant), the required ROI drops (but never below 0.2%).
           This allows 'zombie' positions to exit at breakeven+ rather than holding forever.
        2. Sigma-Based DCA Depth: Grid levels are defined by Standard Deviations from the ENTRY price,
           not the market mean. This relates risk directly to our specific pain point.
        3. Inverse Volatility Sizing: Entry size scales inversely with volatility.
           High Volatility -> Smaller Entry (Safety). Low Volatility -> Larger Entry (Confidence).
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'amt': float, 'entry_price': float, 'ticks_held': int, 'dca_count': int}}
        self.history = {}
        self.window_size = 60
        
        # Risk Parameters
        self.base_bet_cash = 200.0
        self.max_dca_levels = 6
        self.dca_multiplier = 1.5      # Geometric scaling to average down efficiently
        self.min_roi_floor = 0.002     # Absolute minimum profit 0.2%
        self.start_roi = 0.02          # Target 2% initially
        
        # Entry Filters
        self.z_entry_threshold = -2.6  # Strict oversold condition
        
    def _get_stats(self, symbol, current_price):
        if symbol not in self.history or len(self.history[symbol]) < self.window_size:
            return None
            
        prices = self.history[symbol]
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices) if len(prices) > 1 else 0.0
        
        if stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        return {'mean': mean, 'stdev': stdev, 'z': z_score}

    def on_price_update(self, prices):
        # 1. Update Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            # Increment hold duration
            if sym in self.portfolio:
                self.portfolio[sym]['ticks_held'] += 1

        # 2. Evaluate Strategy
        for sym, price in prices.items():
            stats = self._get_stats(sym, price)
            if not stats:
                continue
                
            position = self.portfolio.get(sym)
            
            if position:
                # --- EXIT LOGIC (NO STOP LOSS) ---
                # Calculate dynamic ROI target based on holding time
                # Decay rate: drops 0.01% per tick held
                roi_decay = position['ticks_held'] * 0.0001 
                current_target_roi = max(self.min_roi_floor, self.start_roi - roi_decay)
                
                # Strict check: Price must be above entry by target %
                exit_price = position['entry_price'] * (1 + current_target_roi)
                
                if price >= exit_price:
                    # Realize Profit
                    pnl = (price - position['entry_price']) * position['amt']
                    self.capital += position['amt'] * price
                    del self.portfolio[sym]
                    
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': position['amt'],
                        'reason': ['PROFIT_CAPTURE', f'ROI_{current_target_roi:.4f}']
                    }
                
                # --- DCA LOGIC (DEFENSE) ---
                if position['dca_count'] < self.max_dca_levels:
                    # Calculate drop in Sigmas relative to our Entry Price
                    dist_sigma = (price - position['entry_price']) / stats['stdev']
                    
                    # Progressive spacing: Level 1 needs -2 sigma, Level 2 needs -3 sigma...
                    # This prevents buying too rapidly in a crash
                    required_sigma = -2.0 - (position['dca_count'] * 1.0)
                    
                    if dist_sigma < required_sigma:
                        buy_amt = position['amt'] * self.dca_multiplier
                        cost = buy_amt * price
                        
                        if self.capital >= cost:
                            self.capital -= cost
                            
                            # Average Down Math
                            total_amt = position['amt'] + buy_amt
                            total_cost = (position['amt'] * position['entry_price']) + cost
                            new_entry = total_cost / total_amt
                            
                            self.portfolio[sym] = {
                                'amt': total_amt,
                                'entry_price': new_entry,
                                'ticks_held': position['ticks_held'], # Persist time
                                'dca_count': position['dca_count'] + 1
                            }
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_amt,
                                'reason': ['SIGMA_DCA', f'LVL_{position["dca_count"]+1}']
                            }
            
            else:
                # --- ENTRY LOGIC ---
                if stats['z'] < self.z_entry_threshold:
                    # Inverse Volatility Sizing
                    # Normalized vol ratio (approx 0.001 to 0.05 usually)
                    vol_ratio = stats['stdev'] / price
                    
                    # If vol is high (0.05), mult is small (0.4). If vol is low (0.005), mult is high (2.0).
                    # Formula dampens size during turbulence.
                    safe_vol = max(vol_ratio, 0.001)
                    size_mult = min(3.0, 0.01 / safe_vol) 
                    
                    cash_to_use = self.base_bet_cash * size_mult
                    amount = cash_to_use / price
                    
                    if self.capital >= cash_to_use:
                        self.capital -= cash_to_use
                        self.portfolio[sym] = {
                            'amt': amount,
                            'entry_price': price,
                            'ticks_held': 0,
                            'dca_count': 0
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': amount,
                            'reason': ['INV_VOL_ENTRY', f'Z_{stats["z"]:.2f}']
                        }
                        
        return None