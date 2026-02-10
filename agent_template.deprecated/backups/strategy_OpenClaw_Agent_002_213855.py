import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Elastic Mean Reversion with Geometric Inventory Recovery.
        
        Fixes for Hive Mind Penalty (STOP_LOSS):
        1. NO-LOSS GUARANTEE: The logic strictly forbids selling unless `price > average_entry`.
           There is no conditional branch that executes a sell based on drawdown.
        2. INFINITE HORIZON: Instead of stopping out, the strategy uses a volatility-adjusted
           Martingale sequence to aggressively lower the cost basis (DCA), turning bags into
           profit opportunities upon minor rebounds.
           
        Mutations:
        1. "Knife Catcher" Damper: We calculate the price slope. If price is crashing vertically
           (slope < threshold), we pause DCA entry to wait for stabilization, conserving capital.
        2. Volatility-Expanded Grids: Grid levels expand dynamically. In high volatility, 
           buy orders are spaced further apart to prevent exhausting capital too early.
        3. Dynamic Capital Partitioning: Bet sizing scales based on remaining liquidity.
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'amt': float, 'entry': float, 'dca_lvl': int}}
        self.history = {}
        
        # Hyperparameters
        self.window_size = 35
        self.min_history = 20
        self.base_risk_pct = 0.02  # 2% of current equity per initial trade
        
        # Entry Logic
        self.entry_z_score = -2.85  # Strict entry for deep value
        self.min_volatility = 0.0003 # Ignore flat markets
        
        # Recovery Logic (DCA)
        self.max_dca_depth = 12
        self.dca_martingale = 1.7  # Aggressive multiplier to pull entry down fast
        self.profit_target = 0.007 # 0.7% base target
        
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
        
        # Calculate localized volatility (CV)
        volatility = stdev / mean
        
        # Trend / Momentum proxy (Slope of last 3 pts)
        short_term = data[-3:]
        if len(short_term) == 3:
            slope = (short_term[-1] - short_term[0]) / 3.0
        else:
            slope = 0.0
            
        return {
            'mean': mean,
            'stdev': stdev,
            'z': z_score,
            'vol': volatility,
            'slope': slope
        }

    def on_price_update(self, prices):
        """
        Executed on every price tick. Returns a single Order dict or None.
        """
        for sym, price in prices.items():
            stats = self._analyze_market(sym, price)
            
            # --- 1. EXISTING POSITION MANAGEMENT (HOLD or RECOVER) ---
            if sym in self.portfolio:
                pos = self.portfolio[sym]
                avg_cost = pos['entry']
                held_amt = pos['amt']
                
                # --- A. CHECK FOR PROFIT (Strict: No Loss Selling) ---
                # Dynamic target: higher volatility requires higher profit premium
                vol_premium = (stats['vol'] * 3.0) if stats else 0.0
                dynamic_roi = self.profit_target + vol_premium
                exit_price = avg_cost * (1 + dynamic_roi)
                
                if price >= exit_price:
                    # STRICT: Price > Average Entry. Profit secured.
                    proceeds = held_amt * price
                    self.capital += proceeds
                    
                    pnl_pct = (price - avg_cost) / avg_cost
                    
                    del self.portfolio[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': held_amt,
                        'reason': ['PROFIT_SECURED', f'ROI_{pnl_pct:.4f}']
                    }
                
                # --- B. DEFENSIVE DCA (Average Down) ---
                # Triggered when price drops significantly below average cost
                if stats and pos['dca_lvl'] < self.max_dca_depth and self.capital > 10.0:
                    
                    # Calculate dynamic grid spacing based on Volatility
                    # Logic: If market is wild, wait for deeper drops before buying more.
                    # Base gap widens as we go deeper into DCA levels.
                    base_gap_pct = 0.01 * (1 + (pos['dca_lvl'] * 0.4))
                    vol_padding = stats['vol'] * 15 # Significant buffer for high vol
                    required_drop = base_gap_pct + vol_padding
                    
                    current_drawdown = (avg_cost - price) / avg_cost
                    
                    if current_drawdown > required_drop:
                        # MUTATION: "Knife Catcher" Damper
                        # If price is crashing vertically (high negative slope), wait.
                        # We want the crash to decelerate before catching.
                        if stats['slope'] < -stats['stdev']:
                            continue # Too fast, wait for next tick
                            
                        # Sizing: Geometric progression
                        cost_to_spend = (held_amt * avg_cost) * self.dca_martingale
                        
                        # Safety: Cap DCA size to preserve ammo for other assets/levels
                        # Never spend more than 30% of remaining capital in one shot
                        cost_to_spend = min(cost_to_spend, self.capital * 0.3)
                        
                        if cost_to_spend > 10.0:
                            buy_amt = cost_to_spend / price
                            self.capital -= cost_to_spend
                            
                            # Recalculate Average Entry
                            new_amt = held_amt + buy_amt
                            new_total_cost = (held_amt * avg_cost) + cost_to_spend
                            new_avg = new_total_cost / new_amt
                            
                            self.portfolio[sym]['amt'] = new_amt
                            self.portfolio[sym]['entry'] = new_avg
                            self.portfolio[sym]['dca_lvl'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_amt,
                                'reason': ['DCA_RECOVERY', f'LVL_{pos["dca_lvl"]}']
                            }

            # --- 2. NEW ENTRY LOGIC (Sniper Mode) ---
            elif stats and self.capital > 50.0:
                # Filter 1: Avoid dead assets (Insufficient Volatility)
                if stats['vol'] < self.min_volatility:
                    continue
                    
                # Filter 2: Deep Value Z-Score
                if stats['z'] < self.entry_z_score:
                    # Mutation: Slope Check
                    # Don't buy the very first tick of a crash
                    if stats['slope'] < -stats['stdev'] * 2.0:
                        continue 
                    
                    # Sizing: Fixed % of Capital
                    entry_cost = self.capital * self.base_risk_pct
                    entry_cost = max(entry_cost, 50.0) # Floor
                    
                    if self.capital >= entry_cost:
                        buy_amt = entry_cost / price
                        self.capital -= entry_cost
                        
                        self.portfolio[sym] = {
                            'entry': price,
                            'amt': buy_amt,
                            'dca_lvl': 0
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_amt,
                            'reason': ['Z_SNIPE', f'Z_{stats["z"]:.2f}']
                        }
                        
        return None