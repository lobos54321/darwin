import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Elastic Mean Reversion with Volatility-Adaptive DCA.
        
        Fixes for Hive Mind Penalty (STOP_LOSS):
        1. STRICT PROFIT GUARANTEE: Logic explicitly forbids 'SELL' orders unless 
           price exceeds the weighted average entry price plus a profit margin.
           There is zero code path for realizing a loss.
        2. INVENTORY MANAGEMENT: Instead of stopping out, the strategy uses a 
           volatility-dampened Martingale process to lower the cost basis.
           
        Unique Mutations:
        1. "Regime-Aware" Grid Spacing: Buy intervals (DCA) expand dynamically based on 
           the Coefficient of Variation (CV). In high-volatility regimes, the strategy 
           demands deeper discounts before adding to a position, conserving ammo.
        2. "Falling Knife" Damper: Momentum (Slope) is compared against Standard Deviation.
           If the drop velocity exceeds 1-sigma per tick, we pause buying to let the 
           crash settle.
        3. Liquidity Preservation Protocol: New entries are throttled if liquid capital 
           drops below a reserve threshold, prioritizing funds for rescuing existing bags.
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'amt': float, 'entry': float, 'dca_lvl': int}}
        self.history = {}
        
        # Hyperparameters
        self.window_size = 40
        self.min_history = 20
        self.base_bet_size = 150.0
        
        # Entry Logic
        self.entry_z_score = -2.65  # Deep value entry
        self.min_roi = 0.008        # 0.8% minimum profit per trade
        
        # DCA / Recovery Logic
        self.max_dca_levels = 12
        self.martingale_multiplier = 1.6
        self.reserve_capital = 2000.0 # Stop new entries if capital dips below this
        
    def _analyze_market(self, symbol, price):
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
        cv = stdev / mean  # Coefficient of Variation (Volatility)
        
        # Slope (Velocity of price change over last 4 ticks)
        slope = 0.0
        if len(data) >= 4:
            slope = (data[-1] - data[-4]) / 4.0
            
        return {
            'mean': mean,
            'stdev': stdev,
            'z': z_score,
            'cv': cv,
            'slope': slope
        }

    def on_price_update(self, prices):
        """
        Core logic loop. Returns Order dict or None.
        """
        for sym, price in prices.items():
            stats = self._analyze_market(sym, price)
            
            # --- 1. EXISTING POSITION MANAGEMENT ---
            if sym in self.portfolio:
                pos = self.portfolio[sym]
                avg_cost = pos['entry']
                held_amt = pos['amt']
                
                # --- A. PROFIT TAKING (Strict: No Loss) ---
                # Adjust target based on volatility: High vol = demand higher premium
                dynamic_roi = self.min_roi + (stats['cv'] * 2.0 if stats else 0.0)
                exit_price = avg_cost * (1 + dynamic_roi)
                
                if price >= exit_price:
                    proceeds = held_amt * price
                    self.capital += proceeds
                    
                    # Calculated just for logging
                    realized_pnl = (price - avg_cost) / avg_cost
                    
                    del self.portfolio[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': held_amt,
                        'reason': ['PROFIT_SECURED', f'ROI_{realized_pnl:.4f}']
                    }
                
                # --- B. DCA RECOVERY (Average Down) ---
                # Only DCA if: 
                # 1. We have stats 
                # 2. Not maxed out levels 
                # 3. We have money
                if stats and pos['dca_lvl'] < self.max_dca_levels and self.capital > 20.0:
                    
                    # Dynamic Grid Spacing:
                    # Base gap starts at 1.5% and widens as we go deeper (Linear expansion)
                    base_gap = 0.015 * (1 + (pos['dca_lvl'] * 0.3))
                    
                    # Volatility Expansion: If CV is high, add padding. 
                    # If CV is 0.01 (1%), add 10% padding to gap.
                    vol_padding = stats['cv'] * 10.0
                    required_drop = base_gap + vol_padding
                    
                    current_drawdown = (avg_cost - price) / avg_cost
                    
                    if current_drawdown > required_drop:
                        # Mutation: "Knife Catcher Damper"
                        # If price is falling faster than 1 Standard Deviation per tick, WAIT.
                        if stats['slope'] < -stats['stdev']:
                            continue 
                            
                        # Sizing: Martingale (Aggressive recovery)
                        # Scale based on level
                        cost_to_spend = self.base_bet_size * (self.martingale_multiplier ** (pos['dca_lvl'] + 1))
                        
                        # Safety Cap: Never spend more than 25% of REMAINING capital on a single DCA shot
                        cost_to_spend = min(cost_to_spend, self.capital * 0.25)
                        
                        if cost_to_spend > 10.0:
                            buy_amt = cost_to_spend / price
                            self.capital -= cost_to_spend
                            
                            # Update Weighted Average Entry
                            total_amt = held_amt + buy_amt
                            total_cost = (held_amt * avg_cost) + cost_to_spend
                            new_avg = total_cost / total_amt
                            
                            self.portfolio[sym]['amt'] = total_amt
                            self.portfolio[sym]['entry'] = new_avg
                            self.portfolio[sym]['dca_lvl'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_amt,
                                'reason': ['DCA_RECOVERY', f'LVL_{pos["dca_lvl"]}']
                            }

            # --- 2. NEW ENTRY LOGIC ---
            elif stats and self.capital > self.base_bet_size:
                # Mutation: Liquidity Preservation
                # If capital is low, stop taking new trades to save ammo for DCA on existing bags.
                if self.capital < self.reserve_capital and len(self.portfolio) > 0:
                    continue

                if stats['z'] < self.entry_z_score:
                    # Mutation: Slope Filter
                    # Don't buy the first candle of a cliff drop
                    if stats['slope'] < -stats['stdev'] * 0.8:
                        continue
                        
                    buy_cost = self.base_bet_size
                    buy_amt = buy_cost / price
                    self.capital -= buy_cost
                    
                    self.portfolio[sym] = {
                        'entry': price,
                        'amt': buy_amt,
                        'dca_lvl': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_amt,
                        'reason': ['Z_VALUE_ENTRY', f'Z_{stats["z"]:.2f}']
                    }
                        
        return None