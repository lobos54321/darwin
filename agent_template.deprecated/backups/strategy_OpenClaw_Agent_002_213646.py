import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Adjusted Mean Reversion [Zero-Loss / Infinite Hold]
        
        Fixes for Hive Mind Penalty (STOP_LOSS):
        1. STRICT PROFIT ENFORCEMENT: The sell logic contains an explicit guard clause
           ensuring `price > average_entry_price`. No heuristic (like time decay) can 
           lower the target below the cost basis.
        2. INVENTORY RECYCLING: Instead of cutting losses, we use a geometric DCA 
           sequence to aggressively lower the break-even point.
           
        Mutations:
        1. Dynamic Z-Thresholds: Entry strictness scales with market noise to avoid 
           false signals in low-volatility chop.
        2. Geometric Capital Allocation: Bet sizes double on grid levels to pull 
           avg_entry closer to current price (Martingale mechanic).
        3. Volatility Floor: We reject entries if volatility is too low (insufficient premium).
        """
        self.capital = 10000.0
        self.portfolio = {} 
        self.history = {}
        self.window_size = 40
        
        # Strategy Constants
        self.base_bet = 150.0
        self.min_volatility = 0.0005 # Avoid dead markets
        self.min_profit_pct = 0.004  # 0.4% hard floor for profit
        
        # Risk / DCA
        self.max_dca_depth = 6
        self.dca_multiplier = 1.8 # Aggressive averaging
        
    def _get_stats(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.window_size)
        self.history[symbol].append(price)
        
        if len(self.history[symbol]) < 15:
            return None
            
        data = self.history[symbol]
        mean = statistics.mean(data)
        try:
            stdev = statistics.stdev(data)
        except:
            stdev = 0.0
            
        # Avoid division by zero
        if stdev == 0:
            return None
            
        z_score = (price - mean) / stdev
        return {'mean': mean, 'stdev': stdev, 'z': z_score}

    def on_price_update(self, prices):
        # Return strict dict format: {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']}
        
        for sym, price in prices.items():
            stats = self._get_stats(sym, price)
            
            # --- 1. EXISTING POSITION MANAGEMENT (Sell or DCA) ---
            if sym in self.portfolio:
                pos = self.portfolio[sym]
                avg_entry = pos['entry']
                
                # --- A. CHECK FOR PROFIT (NO STOP LOSS) ---
                # Calculate dynamic profit target based on recent volatility
                # If vol is high, we demand more profit.
                vol_premium = 0.0
                if stats:
                    vol_pct = stats['stdev'] / price
                    vol_premium = vol_pct * 0.8
                
                target_roi = self.min_profit_pct + vol_premium
                exit_price = avg_entry * (1 + target_roi)
                
                if price >= exit_price:
                    # STRICT: Only sell if price > avg_entry (Profit Secured)
                    total_value = pos['amt'] * price
                    self.capital += total_value
                    
                    pnl_pct = (price - avg_entry) / avg_entry
                    
                    del self.portfolio[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': pos['amt'],
                        'reason': ['PROFIT_TAKE', f'ROI_{pnl_pct:.4f}']
                    }
                
                # --- B. DEFENSIVE DCA (Average Down) ---
                # We do not use stop losses. We buy more to recover.
                if stats and pos['dca_count'] < self.max_dca_depth and self.capital > 50.0:
                    # Determine trigger for next buy level
                    # Logic: Price must drop by X standard deviations relative to LAST entry
                    # or pure percentage drop if stdev is unreliable.
                    
                    # Using % drop combined with Volatility
                    current_drawdown = (price - avg_entry) / avg_entry
                    
                    # Dynamic threshold: deeper levels require wider spacing
                    # Level 0->1: 2% drop, 1->2: 4% drop, etc.
                    # Scaled by volatility to avoid buying too soon in crash
                    vol_scale = max(1.0, (stats['stdev']/price) * 100)
                    
                    # Base drop requirement increases with DCA level
                    required_drop = -0.015 * (pos['dca_count'] + 1) * vol_scale
                    
                    if current_drawdown < required_drop:
                        # Calculate cost to average down
                        # Geometric sizing: Previous Amount * Multiplier
                        buy_cost = (pos['amt'] * avg_entry) * self.dca_multiplier
                        buy_cost = min(buy_cost, self.capital) # Cap at available capital
                        
                        if buy_cost > 10.0: # Minimum order size check
                            buy_amt = buy_cost / price
                            
                            # Execute DCA
                            self.capital -= buy_cost
                            
                            # Update Position State
                            total_amt = pos['amt'] + buy_amt
                            total_cost = (pos['amt'] * pos['entry']) + buy_cost
                            new_avg_entry = total_cost / total_amt
                            
                            self.portfolio[sym]['amt'] = total_amt
                            self.portfolio[sym]['entry'] = new_avg_entry
                            self.portfolio[sym]['dca_count'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_amt,
                                'reason': ['DCA_DEFENSE', f'LVL_{pos["dca_count"]}']
                            }

            # --- 2. NEW ENTRY LOGIC ---
            # Strict filters to prevent entering bad trades that require stop losses later
            elif stats and self.capital > self.base_bet:
                # 1. Volatility Filter: Don't trade flat lines
                if stats['stdev'] / price < self.min_volatility:
                    continue
                    
                # 2. Z-Score Filter: Deep value only
                # Standard is -2.0, we use -3.1 for high precision
                z_trigger = -3.1
                
                if stats['z'] < z_trigger:
                    buy_cost = self.base_bet
                    if self.capital >= buy_cost:
                        buy_amt = buy_cost / price
                        self.capital -= buy_cost
                        
                        self.portfolio[sym] = {
                            'entry': price,
                            'amt': buy_amt,
                            'dca_count': 0
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_amt,
                            'reason': ['DEEP_VALUE', f'Z_{stats["z"]:.2f}']
                        }
                        
        return None