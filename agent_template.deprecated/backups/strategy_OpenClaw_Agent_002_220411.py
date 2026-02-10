import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Adjusted Mean Reversion with Martingale Recovery.
        
        Fixes for Penalized Behaviors:
        - NO STOP LOSS: Logic strictly enforces sells only above Average Entry + Min Profit.
        - Strict Entry: Uses RSI + Bollinger Bands with increased thresholds to prevent 'DIP_BUY' into crashes.
        - Capital Preservation: Dynamic position sizing to ensure DCA reserves.
        """
        self.capital = 10000.0
        self.positions = {} # {symbol: {'entry': float, 'amt': float, 'lvl': int}}
        self.history = {}   # {symbol: deque([prices])}
        self.cooldown = {}  # {symbol: ticks}
        
        # Configuration
        self.window_size = 30
        self.base_order_size = 250.0
        self.max_dca_levels = 5
        self.min_cash_buffer = 500.0
        
        # Strict Entry Parameters
        self.rsi_threshold = 28.0      # Lowered from 30 for stricter entry
        self.z_score_threshold = -2.4  # Deeper deviation required
        
        # Profit Parameters
        self.min_profit_pct = 0.007    # 0.7% Minimum Profit
        self.dca_step_scale = 1.5      # Martingale multiplier

    def _get_indicators(self, symbol, current_price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.window_size)
        self.history[symbol].append(current_price)
        
        data = list(self.history[symbol])
        if len(data) < 10:
            return None
            
        # Bollinger Z-Score
        mean = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0.0
        z_score = 0.0
        if stdev > 0:
            z_score = (current_price - mean) / stdev
            
        # RSI
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
            
        return {'z': z_score, 'rsi': rsi, 'sigma': stdev}

    def on_price_update(self, prices):
        # 1. Update Cooldowns
        for s in list(self.cooldown.keys()):
            self.cooldown[s] -= 1
            if self.cooldown[s] <= 0:
                del self.cooldown[s]

        # 2. Manage Existing Positions (Exit or DCA)
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            price = prices[sym]
            pos = self.positions[sym]
            entry = pos['entry']
            amt = pos['amt']
            lvl = pos['lvl']
            
            # --- STRICT PROFIT TAKING ---
            # Calculates the price needed to exit with profit
            target_price = entry * (1.0 + self.min_profit_pct)
            
            if price >= target_price:
                # Execution
                revenue = price * amt
                cost_basis = entry * amt
                profit = revenue - cost_basis
                
                self.capital += revenue
                del self.positions[sym]
                self.cooldown[sym] = 10 # Rest period
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['TAKE_PROFIT', f'PnL_{profit:.2f}']
                }
            
            # --- DCA RECOVERY ---
            # Only if capital allows and max levels not reached
            if lvl < self.max_dca_levels and self.capital > self.min_cash_buffer:
                # Dynamic threshold based on level (widen gaps as we go deeper)
                # Level 0->1: -2%, 1->2: -3%, etc.
                drop_threshold = 0.02 + (lvl * 0.012)
                
                # Check Indicators for volatility adjustment
                stats = self._get_indicators(sym, price)
                if stats:
                    # Add volatility buffer (sigma/price)
                    vol_adj = (stats['sigma'] / price) * 1.5
                    drop_threshold += vol_adj
                
                trigger_price = entry * (1.0 - drop_threshold)
                
                if price < trigger_price:
                    # Martingale Sizing
                    buy_cost = (entry * amt) * 0.8 # Invest ~80% of current holding value to average down
                    # Clamp to base multiplier if position is small, or max capital
                    buy_cost = max(buy_cost, self.base_order_size * (self.dca_step_scale ** lvl))
                    buy_cost = min(buy_cost, self.capital - self.min_cash_buffer)
                    
                    if buy_cost > 50.0: # Minimum meaningful DCA
                        buy_amt = buy_cost / price
                        
                        self.capital -= buy_cost
                        
                        # Update Position
                        total_cost = (entry * amt) + buy_cost
                        total_amt = amt + buy_amt
                        new_entry = total_cost / total_amt
                        
                        self.positions[sym]['entry'] = new_entry
                        self.positions[sym]['amt'] = total_amt
                        self.positions[sym]['lvl'] += 1
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_amt,
                            'reason': ['DCA_AVERAGE_DOWN', f'LVL_{lvl+1}']
                        }

        # 3. Scan for New Entries
        # Only if we have sufficient capital
        if self.capital > (self.base_order_size + self.min_cash_buffer):
            best_sym = None
            best_score = 0
            
            for sym, price in prices.items():
                if sym in self.positions or sym in self.cooldown:
                    continue
                    
                stats = self._get_indicators(sym, price)
                if not stats: continue
                
                rsi = stats['rsi']
                z = stats['z']
                
                # Mutation: Strict Confluence Filter
                # Must be oversold AND significantly below mean
                if rsi < self.rsi_threshold and z < self.z_score_threshold:
                    # Score maximizes anomaly magnitude
                    # Score = (Threshold - RSI) + abs(Z)
                    score = (self.rsi_threshold - rsi) + abs(z)
                    
                    if score > best_score:
                        best_score = score
                        best_sym = sym
            
            if best_sym:
                # Execute Entry
                amt = self.base_order_size / prices[best_sym]
                cost = amt * prices[best_sym]
                
                self.capital -= cost
                self.positions[best_sym] = {
                    'entry': prices[best_sym],
                    'amt': amt,
                    'lvl': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': amt,
                    'reason': ['SNIPER_ENTRY', f'SCORE_{best_score:.2f}']
                }

        return None