import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Diamond-Hands Mean Reversion.
        
        Addressing Hive Mind Penalties:
        1. STOP_LOSS: Logic explicitly forbids selling if ROI <= minimal_threshold. 
           We treat every position as an investment until it turns green.
        2. DIP_BUY: Entry criteria tightened significantly. 
           - RSI must be extremely oversold (< 20).
           - Z-Score must be deeply negative (< -3.2).
           - This ensures we only catch the "blood in the streets" moments, avoiding early knife-catching.
           
        Mutations:
        1. Adaptive DCA Gaps: The distance between DCA buys expands based on the DCA level.
           Level 1 gap is 2%, Level 2 is 4%, etc. This preserves capital during prolonged crashes.
        2. Dynamic Profit Taking: Heavy bags (high DCA levels) exit at lower ROI to free up liquidity quickly.
        """
        # Capital Management
        self.balance = 2000.0
        self.base_bet = 50.0
        self.max_positions = 3
        
        # Martingale / DCA Settings
        self.max_dca_levels = 5
        self.dca_multiplier = 1.6  # Aggressive size scaling to lower avg price
        self.base_dca_gap = 0.02   # Start with 2% gap
        
        # Entry Settings (Strict)
        self.lookback = 40
        self.entry_rsi = 22.0      # Very strict oversold
        self.entry_z = -3.2        # Statistical outlier
        
        # Exit Settings (Profit Only)
        self.target_roi = 0.02     # 2% Standard target
        self.min_roi = 0.005       # 0.5% Minimum survival profit
        
        # State
        self.positions = {}        # symbol -> {avg_price, quantity, dca_levels, last_price}
        self.history = {}          # symbol -> deque([prices])

    def _analyze(self, data):
        """Calculates statistical indicators."""
        if len(data) < self.lookback:
            return None
            
        window = list(data)[-self.lookback:]
        current_price = window[-1]
        
        # Basic Stats
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        if stdev == 0: return None
        
        z_score = (current_price - mean) / stdev
        
        # RSI Calculation (Smoothed)
        gains = 0.0
        losses = 0.0
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0: gains += delta
            else: losses += abs(delta)
            
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        # 1. Update Market Data & Indicators
        market_metrics = {}
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback + 5)
            self.history[symbol].append(price)
            
            metrics = self._analyze(self.history[symbol])
            if metrics:
                market_metrics[symbol] = metrics

        # 2. Check EXITS (Strictly Profit Only - No Stop Loss)
        # We iterate a copy of keys to modify the dict safely if needed (though we return immediately usually)
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]
            avg_price = pos['avg_price']
            qty = pos['quantity']
            
            # ROI Calculation
            roi = (current_price - avg_price) / avg_price
            
            # DETERMINISTIC RULE: If ROI is negative, we DO NOT SELL.
            # This directly addresses the STOP_LOSS penalty.
            if roi <= 0:
                continue
                
            # Dynamic Target: If we are deep in DCA (heavy bag), take profit sooner to release risk.
            # Level 0: Target 2.0%
            # Level 4+: Target 0.5%
            required_roi = max(self.min_roi, self.target_roi - (pos['dca_levels'] * 0.004))
            
            if roi >= required_roi:
                # Execute Sell
                self.balance += current_price * qty
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f"ROI_{roi:.2%}"]
                }

        # 3. Check DCA (Defend Position)
        for symbol, pos in self.positions.items():
            if symbol not in prices: continue
            if pos['dca_levels'] >= self.max_dca_levels: continue
            
            current_price = prices[symbol]
            last_price = pos['last_price']
            
            # Calculate drop from last entry
            drop = (last_price - current_price) / last_price
            
            # Adaptive Gap: Scale gap based on level to widen safety net
            # Level 0->1: 2%, Level 1->2: 3%, etc.
            required_drop = self.base_dca_gap * (1 + (0.5 * pos['dca_levels']))
            
            if drop >= required_drop:
                # Martingale Sizing
                bet_cost = self.base_bet * (self.dca_multiplier ** (pos['dca_levels'] + 1))
                
                if self.balance >= bet_cost:
                    buy_qty = bet_cost / current_price
                    
                    # Update average price
                    total_cost = (pos['quantity'] * pos['avg_price']) + bet_cost
                    total_qty = pos['quantity'] + buy_qty
                    
                    pos['avg_price'] = total_cost / total_qty
                    pos['quantity'] = total_qty
                    pos['dca_levels'] += 1
                    pos['last_price'] = current_price
                    
                    self.balance -= bet_cost
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': ['DCA_DEFEND', f"Lvl_{pos['dca_levels']}"]
                    }

        # 4. Check ENTRIES (Sniper Mode)
        if len(self.positions) < self.max_positions and self.balance >= self.base_bet:
            candidates = []
            for symbol, metrics in market_metrics.items():
                if symbol in self.positions: continue
                
                # Strict Entry Conditions (Fix for DIP_BUY penalty)
                if metrics['z'] < self.entry_z and metrics['rsi'] < self.entry_rsi:
                    candidates.append((symbol, metrics['z']))
            
            if candidates:
                # Pick the most statistically deviated asset
                candidates.sort(key=lambda x: x[1])
                best_sym = candidates[0][0]
                price = prices[best_sym]
                
                qty = self.base_bet / price
                
                self.positions[best_sym] = {
                    'avg_price': price,
                    'quantity': qty,
                    'dca_levels': 0,
                    'last_price': price
                }
                
                self.balance -= self.base_bet
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': qty,
                    'reason': ['SNIPER_ENTRY', f"Z_{candidates[0][1]:.2f}"]
                }

        return None