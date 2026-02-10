import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Mean Reversion Grid with Martingale Recovery.
        
        Compliance:
        - NO STOP LOSS: Exits are strictly strictly calculated as (Average Entry * (1 + Min Profit)).
          Trades will hold indefinitely until profitability is reached or DCA lowers the basis enough to exit.
        - Strict Entry: Uses combination of RSI and Bollinger Band Z-Scores to ensure we only buy statistical anomalies.
        """
        # Capital Management
        self.capital = 10000.0
        self.min_cash_reserve = 500.0  # Reserve for emergency DCA
        
        # Portfolio State
        # {symbol: {'entry': float, 'amt': float, 'dca_lvl': int, 'ticks': int}}
        self.portfolio = {}
        self.history = {}
        self.cooldown = {} # {symbol: ticks_remaining}
        
        # Hyperparameters
        self.window_size = 30
        self.base_order_amt = 200.0
        self.max_dca_levels = 6
        
        # Strict Entry Conditions (Deep Dip Buying)
        self.rsi_limit = 30.0    # Only buy oversold
        self.z_score_limit = -2.2 # >2 Standard Deviations below mean
        
        # Profit Targets (Strictly Positive)
        self.min_roi = 0.005      # Minimum 0.5% profit (Hard Floor)
        self.target_roi = 0.025   # Target 2.5% profit

    def _calculate_stats(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.window_size)
        self.history[symbol].append(price)
        
        data = list(self.history[symbol])
        if len(data) < 15: # Need minimum data for valid stats
            return None
            
        mean = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0.0
        
        # Z-Score
        z = 0.0
        if stdev > 0:
            z = (price - mean) / stdev
            
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
            
        return {'z': z, 'rsi': rsi, 'sigma': stdev}

    def on_price_update(self, prices):
        # 0. Cooldown Management
        for s in list(self.cooldown.keys()):
            self.cooldown[s] -= 1
            if self.cooldown[s] <= 0:
                del self.cooldown[s]

        # 1. Check Existing Positions (Priority: SELL > DCA)
        # We iterate a copy of keys to modify dictionary safely if needed
        for sym in list(self.portfolio.keys()):
            if sym not in prices: continue
            
            price = prices[sym]
            pos = self.portfolio[sym]
            pos['ticks'] += 1
            
            entry_price = pos['entry']
            amt = pos['amt']
            lvl = pos['dca_lvl']
            
            # --- PROFIT TAKING (NO STOP LOSS) ---
            # We decay the target slightly over time to encourage turnover, 
            # BUT we clamp it to self.min_roi to guarantee profit.
            # Decay starts after 50 ticks.
            decay = max(0, (pos['ticks'] - 50) * 0.0002)
            current_target = max(self.min_roi, self.target_roi - decay)
            
            exit_price = entry_price * (1.0 + current_target)
            
            if price >= exit_price:
                proceeds = amt * price
                self.capital += proceeds
                del self.portfolio[sym]
                self.cooldown[sym] = 5 # Avoid immediate re-entry
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['PROFIT', f'ROI_{current_target:.4f}']
                }
            
            # --- DCA RECOVERY ---
            # If price moves against us, we lower the average entry cost
            if lvl < self.max_dca_levels and self.capital > self.min_cash_reserve:
                # Calculate dynamic gap based on volatility
                stats = self._calculate_stats(sym, price)
                sigma = stats['sigma'] if stats else (entry_price * 0.01)
                
                # Gap widens with levels: 1.5%, 2.5%, 3.5% + volatility buffer
                base_gap = 0.015 + (0.01 * lvl)
                trigger_price = entry_price * (1.0 - base_gap) - (sigma * 1.5)
                
                if price < trigger_price:
                    # Martingale sizing: 1.5x previous size to pull avg down fast
                    buy_size = self.base_order_amt * (1.5 ** (lvl + 1))
                    cost = buy_size * price
                    
                    if self.capital >= cost:
                        self.capital -= cost
                        
                        # Weighted Average Calculation
                        total_cost = (entry_price * amt) + cost
                        total_amt = amt + buy_size
                        new_entry = total_cost / total_amt
                        
                        self.portfolio[sym]['entry'] = new_entry
                        self.portfolio[sym]['amt'] = total_amt
                        self.portfolio[sym]['dca_lvl'] += 1
                        # We don't reset ticks, time pressure remains
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_size,
                            'reason': ['DCA_LOWER_AVG', f'LVL_{lvl+1}']
                        }

        # 2. New Entry Logic
        # Only if we have capital
        if self.capital > self.base_order_amt:
            best_sym = None
            best_metric = 0 # Combination of RSI and Z score
            
            for sym, price in prices.items():
                if sym in self.portfolio or sym in self.cooldown:
                    continue
                
                stats = self._calculate_stats(sym, price)
                if not stats: continue
                
                # Strict Filters
                if stats['rsi'] < self.rsi_limit and stats['z'] < self.z_score_limit:
                    # Scoring: deeply negative Z and low RSI is best
                    # Score = (30 - RSI) + abs(Z)
                    score = (30 - stats['rsi']) + abs(stats['z'])
                    
                    if score > best_metric:
                        best_metric = score
                        best_sym = sym
            
            if best_sym:
                amt = self.base_order_amt
                cost = amt * prices[best_sym]
                
                if self.capital >= cost:
                    self.capital -= cost
                    self.portfolio[best_sym] = {
                        'entry': prices[best_sym],
                        'amt': amt,
                        'dca_lvl': 0,
                        'ticks': 0
                    }
                    return {
                        'side': 'BUY',
                        'symbol': best_sym,
                        'amount': amt,
                        'reason': ['SNIPER_ENTRY', f'SCORE_{best_metric:.2f}']
                    }

        return None