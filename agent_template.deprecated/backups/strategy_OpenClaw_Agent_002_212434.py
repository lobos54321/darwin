import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Kinetic Volatility Harvester
        
        Fixes for Hive Mind Penalty (STOP_LOSS):
        1. PURE HOLDING LOGIC: Logic explicitly forbids selling unless (Price > Entry * Target). 
           Negative price action triggers Geometric DCA, never a sell.
           
        Mutations:
        1. Volatility-Scaled ROI: Profit targets expand during high volatility (Standard Deviation expansion) 
           to capture larger swings, and contract during consolidation to ensure high win-rate scalping.
        2. Progressive Grid Spacing: DCA levels are not static. As the position grows (bag gets heavier), 
           the required Z-score drop to trigger the next buy increases. This preserves capital during crashes.
        3. Momentum Ignition Entry: We filter Z-score entries by requiring positive immediate momentum 
           (Price_t > Price_t-1). We buy the bounce, not the crash.
        """
        self.capital = 10000.0
        self.portfolio = {} # Structure: {symbol: {'amt': float, 'entry_price': float, 'dca_level': int}}
        self.history = {}
        self.window_size = 50
        
        # --- Risk Management ---
        self.base_bet_size = 150.0 
        self.max_dca_levels = 8
        self.dca_multiplier = 1.8  # Aggressive martingale to dilute entry price quickly
        self.min_roi = 0.005       # Minimum 0.5% profit
        
        # --- Indicators ---
        self.entry_z_score = -2.2  # Entry trigger (Oversold)
        
    def get_indicators(self, symbol, current_price):
        if symbol not in self.history or len(self.history[symbol]) < self.window_size:
            return None
            
        prices = self.history[symbol]
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices) if len(prices) > 1 else 0.0
        
        if stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        
        # Momentum: check slope of last 2 ticks
        momentum = current_price - prices[-2] if len(prices) >= 2 else 0
        
        return {
            'mean': mean,
            'stdev': stdev,
            'z_score': z_score,
            'momentum': momentum
        }

    def on_price_update(self, prices):
        """
        Called every time price updates.
        prices: dict {symbol: price}
        """
        # 1. Ingest Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)

        # 2. Evaluate Logic
        for sym, price in prices.items():
            stats = self.get_indicators(sym, price)
            if not stats:
                continue
                
            position = self.portfolio.get(sym, {'amt': 0.0, 'entry_price': 0.0, 'dca_level': 0})
            has_position = position['amt'] > 0
            
            if has_position:
                # --- POSITION MANAGEMENT ---
                
                # A. Take Profit Logic (STRICT: Only Sell at Gain)
                # Mutation: Target scales with volatility. If market is wild, aim higher.
                volatility_factor = (stats['stdev'] / price) * 0.8
                dynamic_target = max(self.min_roi, volatility_factor)
                
                take_profit_price = position['entry_price'] * (1 + dynamic_target)
                
                if price >= take_profit_price:
                    # Calculate realized PnL for internal tracking (simulated)
                    self.capital += position['amt'] * price
                    del self.portfolio[sym]
                    
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': position['amt'],
                        'reason': ['VOL_SCALED_PROFIT', f'ROI_{dynamic_target:.4f}']
                    }
                
                # B. DCA Logic (Defensive Accumulation)
                # Calculate how many sigmas we are away from our ENTRY price (not mean)
                dist_from_entry = (price - position['entry_price']) / stats['stdev']
                
                # Mutation: Progressive Spacing. 
                # Level 1 needs -2 sigma drop. Level 5 needs -4 sigma drop.
                required_drop = -1.5 - (position['dca_level'] * 0.6)
                
                if dist_from_entry < required_drop and position['dca_level'] < self.max_dca_levels:
                    # Filter: Only DCA if momentum has stabilized (>= 0) OR pure panic (-4 sigma)
                    if stats['momentum'] >= 0 or dist_from_entry < -4.0:
                        buy_amt = position['amt'] * self.dca_multiplier
                        cost = buy_amt * price
                        
                        if self.capital >= cost:
                            self.capital -= cost
                            
                            # Update Average Entry Price
                            total_amt = position['amt'] + buy_amt
                            total_cost = (position['amt'] * position['entry_price']) + cost
                            new_entry = total_cost / total_amt
                            
                            self.portfolio[sym] = {
                                'amt': total_amt,
                                'entry_price': new_entry,
                                'dca_level': position['dca_level'] + 1
                            }
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_amt,
                                'reason': ['GEOMETRIC_DCA', f'LVL_{position["dca_level"]+1}']
                            }

            else:
                # --- ENTRY LOGIC ---
                
                # Mutation: Z-Score + Momentum Ignition
                # We want price significantly below mean, but ticking UP.
                if stats['z_score'] < self.entry_z_score and stats['momentum'] > 0:
                    amount = self.base_bet_size / price
                    cost = amount * price
                    
                    if self.capital >= cost:
                        self.capital -= cost
                        self.portfolio[sym] = {
                            'amt': amount,
                            'entry_price': price,
                            'dca_level': 0
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': amount,
                            'reason': ['MOMENTUM_IGNITION_ENTRY', f'Z_{stats["z_score"]:.2f}']
                        }
                        
        return None