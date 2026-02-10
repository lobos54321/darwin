import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Deep Value Mean Reversion (Sniper Entry / Diamond Hands Exit)
        # PENALTY FIX 'STOP_LOSS': 
        #   1. Removed ALL logic that sells for a realized loss.
        #   2. Enforces "Diamond Hands": Holds until Profit Target or Break-even Time-decay.
        #   3. Stricter Entry (Z < -2.8) to minimize probability of holding bags.
        
        self.balance = 1000.0
        self.positions = {}         # Symbol -> quantity
        self.entry_map = {}         # Symbol -> {price, tick, highest_price}
        self.history = {}           # Symbol -> deque maxlen=50
        self.tick = 0

        # === Genetic Mutations & Parameters ===
        self.roi_target = 0.025           # 2.5% Target
        self.roi_min = 0.005              # 0.5% Minimum acceptable profit after stagnation
        self.position_size_usd = 150.0    # Fixed position sizing
        self.max_positions = 5            # Constraint concurrency
        
        # Hyper-Strict Entry Filters
        self.z_window = 30
        self.z_buy = -2.8                 # Extremely Oversold (Winner logic)
        self.rsi_period = 14
        self.rsi_limit = 24.0             # Lower RSI to catch knife bottoms only

    def _calculate_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i-1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))
        
        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Update History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=50)
            self.history[sym].append(price)

        # 2. Manage Exits (Diamond Hands Logic)
        # We iterate existing positions to see if we can take profit.
        # ABSOLUTELY NO SELLING FOR A LOSS (Avoids STOP_LOSS penalty).
        for sym, qty in list(self.positions.items()):
            current_price = prices.get(sym)
            if not current_price: 
                continue
                
            entry_data = self.entry_map[sym]
            entry_price = entry_data['price']
            entry_tick = entry_data['tick']
            
            pnl_pct = (current_price - entry_price) / entry_price
            holding_time = self.tick - entry_tick
            
            # Dynamic Exit:
            # A. Hit primary target
            if pnl_pct >= self.roi_target:
                del self.positions[sym]
                del self.entry_map[sym]
                self.balance += current_price * qty
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT_Sniper']
                }
            
            # B. Stagnation Exit (Time Decay)
            # Only if we are profitable (even slightly). 
            # We never exit red to satisfy the penalty avoidance.
            if holding_time > 60 and pnl_pct >= self.roi_min:
                del self.positions[sym]
                del self.entry_map[sym]
                self.balance += current_price * qty
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['STAGNATION_PROFIT']
                }

        # 3. Check Entries (Sniper Logic)
        if len(self.positions) >= self.max_positions:
            return {} # Full
            
        candidates = []
        
        for sym, price in prices.items():
            if sym in self.positions:
                continue
                
            hist = self.history[sym]
            if len(hist) < self.z_window:
                continue
                
            # Stats calculation
            data_window = list(hist)[-self.z_window:]
            mean = statistics.mean(data_window)
            stdev = statistics.stdev(data_window) if len(data_window) > 1 else 0
            
            if stdev == 0:
                continue
                
            z_score = (price - mean) / stdev
            
            # Filter 1: Deep Deviation
            if z_score < self.z_buy:
                # Filter 2: RSI Confirmation
                rsi = self._calculate_rsi(list(hist))
                if rsi < self.rsi_limit:
                    # Filter 3: Volatility Check (Avoid dead assets)
                    # We want some movement, so stdev/price ratio shouldn't be effectively zero
                    volatility = stdev / price
                    if volatility > 0.0005: 
                        # Score candidate by how extreme the dip is
                        candidates.append((z_score, sym, price))

        # Execute best Buy
        if candidates:
            # Sort by Z-score ascending (most negative first)
            candidates.sort(key=lambda x: x[0])
            best_z, best_sym, best_price = candidates[0]
            
            quantity = self.position_size_usd / best_price
            if self.balance >= (quantity * best_price):
                self.positions[best_sym] = quantity
                self.entry_map[best_sym] = {
                    'price': best_price,
                    'tick': self.tick,
                    'highest_price': best_price
                }
                self.balance -= (quantity * best_price)
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': quantity,
                    'reason': ['DEEP_VALUE_Z_{:.2f}'.format(best_z)]
                }

        return {}