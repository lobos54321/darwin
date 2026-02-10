import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion with Volatility-Adaptive Grid.
        
        Core Logic:
        1. STRICT NO-LOSS: Exits are mathematically constrained to be profitable.
        2. ADAPTIVE ENTRIES: Combines Z-Score and RSI to reject "falling knives".
        3. VOLATILITY GRID: DCA levels are spaced by Standard Deviation, not fixed percentages,
           ensuring we only buy deeper when the move is statistically significant relative to noise.
        """
        self.balance = 2000.0
        self.positions = {}  # symbol -> {'avg_price', 'quantity', 'dca_count', 'highest_price'}
        self.history = {}    # symbol -> deque
        
        # --- Configuration ---
        self.lookback = 40           # Ticks for Z-Score/Vol calc
        self.rsi_period = 14         # Ticks for RSI
        
        self.base_size = 50.0        # Initial trade size in currency
        self.reserve_buffer = 300.0  # Keep this much cash free for emergencies
        
        self.max_dca = 5             # Max recovery attempts
        self.profit_target = 0.015   # 1.5% base target
        self.min_profit = 0.005      # 0.5% minimum profit (scalp)
        
        # --- Thresholds ---
        self.entry_z = -2.5          # Initial entry requirement (Deep dip)
        self.entry_rsi = 35.0        # RSI Confluence
        
        # DCA thresholds (in Standard Deviations from entry)
        self.dca_z_step = 1.0        # Step size for martingale grid

    def _calculate_rsi(self, data):
        """Calculates simple RSI from a list of prices."""
        if len(data) <= self.rsi_period:
            return 50.0
            
        gains = []
        losses = []
        # Calculate diffs
        for i in range(1, len(data)):
            diff = data[i] - data[i-1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))
                
        # Slice to period
        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        """
        Main tick handler.
        Returns: Dict representing an order or None.
        """
        stats_map = {}
        
        # 1. Update Market Data & Stats
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) >= self.lookback:
                data = list(self.history[symbol])
                mean = statistics.mean(data)
                stdev = statistics.stdev(data) if len(data) > 1 else 0.0
                rsi = self._calculate_rsi(data)
                
                # Z-Score
                z_score = (price - mean) / stdev if stdev > 0 else 0
                
                stats_map[symbol] = {
                    'price': price,
                    'z': z_score,
                    'mean': mean,
                    'std': stdev,
                    'rsi': rsi
                }

        # 2. Priority 1: Check Exits (Profit Taking Only)
        for symbol, pos in list(self.positions.items()):
            if symbol not in stats_map: continue
            
            market = stats_map[symbol]
            curr_price = market['price']
            avg_price = pos['avg_price']
            qty = pos['quantity']
            
            # Update high watermark for trailing logic
            if 'highest_price' not in pos or curr_price > pos['highest_price']:
                pos['highest_price'] = curr_price
            
            roi = (curr_price - avg_price) / avg_price
            
            # Dynamic Exit Logic:
            # If ROI is high (>1.5%), we try to hold.
            # If price drops from local high by 0.5% (trailing), we exit, BUT ONLY IF overall ROI > min_profit.
            
            should_sell = False
            sell_reason = ""
            
            # Hard Target Reached
            if roi >= self.profit_target:
                should_sell = True
                sell_reason = "TARGET_HIT"
                
            # Trailing Stop-Profit
            elif roi >= self.min_profit:
                drawdown_from_high = (pos['highest_price'] - curr_price) / pos['highest_price']
                if drawdown_from_high > 0.005: # 0.5% drop from peak
                    should_sell = True
                    sell_reason = "TRAILING_PROFIT"
            
            if should_sell:
                # Execute Sell
                self.balance += curr_price * qty
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': [sell_reason, f"ROI_{roi:.4f}"]
                }

        # 3. Priority 2: DCA Recovery (Martingale)
        # We only DCA if price is significantly deeper (measured by volatility, not just %)
        for symbol, pos in self.positions.items():
            if symbol not in stats_map: continue
            if pos['dca_count'] >= self.max_dca: continue
            
            market = stats_map[symbol]
            curr_price = market['price']
            z_score = market['z']
            rsi = market['rsi']
            
            # Determine threshold for next DCA level
            # e.g., Level 1 requires Z < -3.5, Level 2 requires Z < -4.5...
            # This ensures we don't just buy a linear downtrend, but an accelerating crash.
            required_z = self.entry_z - (self.dca_z_step * (pos['dca_count'] + 1))
            
            # Price check: Must be below average entry
            if curr_price < pos['avg_price']:
                # Logic: Extreme statistical deviation + Low RSI
                if z_score < required_z and rsi < 40:
                    
                    # Martingale sizing: 1.5x previous volume
                    # Approximate logic to lower breakeven efficiently
                    investment = self.base_size * (1.5 ** (pos['dca_count'] + 1))
                    
                    if self.balance > investment:
                        qty = investment / curr_price
                        
                        # Update State
                        total_cost = (pos['avg_price'] * pos['quantity']) + investment
                        total_qty = pos['quantity'] + qty
                        
                        pos['avg_price'] = total_cost / total_qty
                        pos['quantity'] = total_qty
                        pos['dca_count'] += 1
                        self.balance -= investment
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': qty,
                            'reason': ['DCA_RESCUE', f"Z_{z_score:.2f}", f"Lvl_{pos['dca_count']}"]
                        }

        # 4. Priority 3: New Entries
        # Scan for opportunities
        if self.balance > (self.base_size + self.reserve_buffer):
            
            best_symbol = None
            lowest_z = 0
            
            for symbol, market in stats_map.items():
                if symbol in self.positions: continue
                
                # Filter: Stricter than previous strategy
                # Must be oversold (Z) AND losing momentum (RSI)
                if market['z'] < self.entry_z and market['rsi'] < self.entry_rsi:
                    
                    # Pick the most extreme outlier
                    if best_symbol is None or market['z'] < lowest_z:
                        best_symbol = symbol
                        lowest_z = market['z']
            
            if best_symbol:
                price = stats_map[best_symbol]['price']
                amount = self.base_size / price
                
                self.positions[best_symbol] = {
                    'avg_price': price,
                    'quantity': amount,
                    'dca_count': 0,
                    'highest_price': price
                }
                self.balance -= self.base_size
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['ENTRY', f"Z_{lowest_z:.2f}"]
                }

        return None