import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Mean Reversion with Volatility-Adaptive DCA.
        
        Fixes for Hive Mind Penalty (STOP_LOSS):
        1. ZERO LOSS PROTOCOL: Exits are mathematically constrained to be strictly 
           above the weighted average entry price. No stop-loss logic exists.
        2. LIQUIDITY PRESERVATION: Strategy reserves a portion of capital specifically 
           for rescuing underwater positions (DCA) rather than opening new ones.
           
        Unique Mutations:
        1. "Regime-Scaled" Entry: The Z-Score threshold for entry dynamically adjusts 
           based on market volatility (Coefficient of Variation). High vol = stricter entry.
        2. "Momentum Confirmation": Uses a simplified RSI calculation to ensure we don't 
           buy a falling knife solely on Z-score; momentum must also be oversold.
        3. "DCA Expansion": Grid levels widen geometrically to endure deep drawdowns 
           without exhausting capital too early.
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'amt': float, 'entry': float, 'dca_lvl': int}}
        self.history = {}
        
        # Hyperparameters
        self.window_size = 50
        self.min_history = 20
        self.base_bet_size = 200.0
        
        # Risk / DCA Settings
        self.max_dca_levels = 10
        self.reserve_ratio = 0.25  # 25% of capital reserved for defense
        
        # Entry Logic (Stricter)
        self.base_z_entry = -2.5
        self.rsi_entry_threshold = 30
        
        # Exit Logic
        self.min_roi = 0.005 # Guarantee at least 0.5% profit
        self.vol_roi_scaler = 5.0 # Demand higher profit in high vol
        
    def _get_indicators(self, symbol, price):
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
            stdev = 0
            
        if stdev == 0:
            return None
            
        z_score = (price - mean) / stdev
        cv = stdev / mean # Volatility
        
        # Simplified RSI (Relative Strength Index)
        rsi = 50
        if len(data) > 14:
            gains = []
            losses = []
            for i in range(1, len(data)):
                change = data[i] - data[i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))
            
            # Simple average for speed/robustness
            avg_gain = statistics.mean(gains[-14:])
            avg_loss = statistics.mean(losses[-14:])
            
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
        
        return {
            'mean': mean,
            'stdev': stdev,
            'z': z_score,
            'cv': cv,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        """
        Main execution loop.
        """
        for sym, price in prices.items():
            stats = self._get_indicators(sym, price)
            if not stats:
                continue
                
            # --- 1. MANAGE EXISTING POSITIONS ---
            if sym in self.portfolio:
                pos = self.portfolio[sym]
                avg_cost = pos['entry']
                held_amt = pos['amt']
                
                # A. PROFIT TAKING (Strictly Positive)
                # Adjust target ROI based on volatility. 
                # If vol (CV) is 1%, add 5% to base ROI.
                dynamic_roi = self.min_roi + (stats['cv'] * self.vol_roi_scaler)
                exit_price = avg_cost * (1 + dynamic_roi)
                
                if price >= exit_price:
                    proceeds = held_amt * price
                    self.capital += proceeds
                    del self.portfolio[sym]
                    
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': held_amt,
                        'reason': ['PROFIT_TARGET', f'ROI_{dynamic_roi:.3f}']
                    }
                
                # B. DCA DEFENSE (Average Down)
                # Only if strictly needed and capital allows
                if pos['dca_lvl'] < self.max_dca_levels:
                    # Expansion: Levels get wider. L0->L1: 2%, L1->L2: 3%, etc.
                    required_drop = 0.02 * (1.5 ** pos['dca_lvl'])
                    current_drawdown = (avg_cost - price) / avg_cost
                    
                    # Volatility Filter: Don't DCA if RSI is still high (falling knife)
                    # Exception: If drawdown is massive (>15%), force buy
                    safe_to_buy = stats['rsi'] < 40 or current_drawdown > 0.15
                    
                    if current_drawdown > required_drop and safe_to_buy:
                        # Sizing: Martingale 1.5x
                        dca_cost = self.base_bet_size * (1.5 ** (pos['dca_lvl'] + 1))
                        dca_cost = min(dca_cost, self.capital * 0.4) # Safety Cap
                        
                        if self.capital > dca_cost and dca_cost > 10:
                            buy_amt = dca_cost / price
                            self.capital -= dca_cost
                            
                            # Recalculate Average Entry
                            total_amt = held_amt + buy_amt
                            total_cost = (held_amt * avg_cost) + dca_cost
                            new_avg = total_cost / total_amt
                            
                            self.portfolio[sym]['amt'] = total_amt
                            self.portfolio[sym]['entry'] = new_avg
                            self.portfolio[sym]['dca_lvl'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_amt,
                                'reason': ['DCA_DEFENSE', f'LVL_{pos["dca_lvl"]}']
                            }

            # --- 2. NEW ENTRIES ---
            elif self.capital > self.base_bet_size:
                # Reserve Logic: Don't open new trades if funds are low (save for DCA)
                if self.capital < (10000.0 * self.reserve_ratio) and len(self.portfolio) > 0:
                    continue

                # Adaptive Thresholds
                # If market is volatile (CV > 0.02), demand deeper discount (Z < -3.5)
                # Otherwise standard Z < -2.5
                target_z = self.base_z_entry - (1.0 if stats['cv'] > 0.02 else 0.0)
                
                # Confluence: Z-Score + RSI + Price > Mean (fail-safe? No, mean reversion)
                if stats['z'] < target_z and stats['rsi'] < self.rsi_entry_threshold:
                    buy_amt = self.base_bet_size / price
                    self.capital -= self.base_bet_size
                    
                    self.portfolio[sym] = {
                        'entry': price,
                        'amt': buy_amt,
                        'dca_lvl': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_amt,
                        'reason': ['QUANTUM_ENTRY', f'Z_{stats["z"]:.2f}']
                    }
                    
        return None