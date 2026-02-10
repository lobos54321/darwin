import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Mean Reversion with Geometric Martingale DCA.
        
        Addressed Penalties:
        - STOP_LOSS: Logic strictly prohibits selling at a loss. Minimum ROI required is 0.6%.
        - DIP_BUY: Entry conditions tightened (Z < -3.0, RSI < 22) to ensure high-probability reversals.
        
        Features:
        - Volatility-adjusted DCA spacing to survive crashes.
        - Geometric position sizing to aggressively lower average cost.
        - Strict Z-score filtering for entries.
        """
        self.balance = 2000.0
        self.positions = {}  # symbol -> {'avg_price', 'quantity', 'dca_count', 'last_dca_price'}
        self.history = {}    # symbol -> deque
        
        # --- Capital Management ---
        self.base_bet = 40.0         # Initial entry size
        self.max_dca_levels = 6      # Maximum DCA additions (Deep pockets)
        self.dca_multiplier = 1.5    # 1.5x martingale multiplier
        
        # --- Entry Parameters (Strict) ---
        self.lookback = 35           # Rolling window size
        self.entry_rsi_limit = 22.0  # Deep oversold condition (Stricter than 25)
        self.entry_z_score = -3.0    # 3-sigma deviation required
        
        # --- Exit Parameters (Strict Profit) ---
        self.min_roi = 0.006         # Minimum 0.6% profit
        self.target_roi = 0.02       # Target 2.0% profit

    def _calculate_indicators(self, data):
        """Calculates Z-Score, RSI, and Volatility."""
        if len(data) < self.lookback:
            return None
            
        # Use recent window
        window = list(data)[-self.lookback:]
        
        # Basic Statistics
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        if stdev == 0: return None
        
        current_price = window[-1]
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean if mean > 0 else 0.0
        
        # RSI Calculation (14 periods)
        deltas = [window[i] - window[i-1] for i in range(1, len(window))]
        gains = [x for x in deltas if x > 0]
        losses = [abs(x) for x in deltas if x < 0]
        
        avg_gain = sum(gains) / 14 if gains else 0.0
        avg_loss = sum(losses) / 14 if losses else 0.0
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'mean': mean,
            'stdev': stdev,
            'z': z_score,
            'rsi': rsi,
            'vol': volatility,
            'price': current_price
        }

    def on_price_update(self, prices):
        """
        Main Loop. Returns one order dict or None.
        Priorities:
        1. SELL (Take Profit)
        2. BUY (DCA Defense)
        3. BUY (New Entry)
        """
        
        # 1. Analyze Market
        market_state = {}
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback + 10)
            self.history[symbol].append(price)
            
            indicators = self._calculate_indicators(self.history[symbol])
            if indicators:
                market_state[symbol] = indicators

        # 2. Check Exits (Priority 1)
        # STRICT: No Stop Loss. Only sell positive ROI.
        for symbol in list(self.positions.keys()):
            if symbol not in market_state: continue
            
            pos = self.positions[symbol]
            stats = market_state[symbol]
            
            current_price = stats['price']
            avg_price = pos['avg_price']
            
            roi = (current_price - avg_price) / avg_price
            
            should_sell = False
            reason = []
            
            # Hit primary target
            if roi >= self.target_roi:
                should_sell = True
                reason = ["TARGET_HIT", f"ROI_{roi:.4f}"]
            
            # Opportunistic exit on indicator exhaustion
            elif roi >= self.min_roi and stats['rsi'] > 70:
                should_sell = True
                reason = ["RSI_EXIT", f"ROI_{roi:.4f}"]
            
            if should_sell:
                qty = pos['quantity']
                self.balance += current_price * qty
                del self.positions[symbol]
                
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': reason
                }

        # 3. Check DCA (Priority 2)
        # Scale into losing positions to improve average price
        for symbol, pos in self.positions.items():
            if symbol not in market_state: continue
            if pos['dca_count'] >= self.max_dca_levels: continue
            
            stats = market_state[symbol]
            current_price = stats['price']
            last_price = pos['last_dca_price']
            
            # Adaptive Gap: Wider gap if volatility is high
            # Base gap 1.5% + (Volatility * 2)
            # This prevents buying too early in a crash
            gap_threshold = 0.015 + (stats['vol'] * 2.0)
            
            price_drop = (last_price - current_price) / last_price
            
            if price_drop > gap_threshold:
                # Filter: Don't catch knife if RSI is still neutral/high
                # We want to buy only if the drop is somewhat confirmed by RSI staying low
                if stats['rsi'] < 45:
                    next_bet = self.base_bet * (self.dca_multiplier ** (pos['dca_count'] + 1))
                    
                    if self.balance > next_bet:
                        amount = next_bet / current_price
                        
                        # Update position in memory
                        total_cost = (pos['avg_price'] * pos['quantity']) + next_bet
                        new_qty = pos['quantity'] + amount
                        
                        pos['avg_price'] = total_cost / new_qty
                        pos['quantity'] = new_qty
                        pos['dca_count'] += 1
                        pos['last_dca_price'] = current_price
                        
                        self.balance -= next_bet
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': amount,
                            'reason': ['DCA', f"Lvl_{pos['dca_count']}"]
                        }

        # 4. Check Entries (Priority 3)
        # Only if we have cash
        if self.balance > self.base_bet:
            candidates = []
            for symbol, stats in market_state.items():
                if symbol in self.positions: continue
                
                # Strict Filters: Deep Value Only
                if stats['z'] < self.entry_z_score and stats['rsi'] < self.entry_rsi_limit:
                    candidates.append((symbol, stats))
            
            # Pick the most oversold (lowest Z-score)
            if candidates:
                candidates