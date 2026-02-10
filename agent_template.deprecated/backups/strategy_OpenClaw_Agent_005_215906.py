import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Adaptive Martingale with Iron-Hand Holding.
        
        Fixes for Penalties:
        1. STOP_LOSS: Logic explicitly requires ROI > 0 to Sell. No stop loss condition exists.
        2. DIP_BUY: Entry conditions tightened (Z-Score < -3.2, RSI < 25) to avoid early entry.
        
        Mutations:
        - Dynamic DCA Spacing: The gap between DCA levels expands as volatility increases.
          This prevents exhausting capital on small dips during high-volatility crashes.
        - Concentrated Portfolio: Limits max positions to ensure sufficient capital 
          is reserved for deep Martingale levels on active positions.
        """
        # --- Capital Management ---
        self.balance = 2000.0
        self.base_bet = 40.0          # Initial bet size
        self.max_positions = 4        # Limit concurrent positions to preserve 'dry powder'
        
        # --- Martingale Parameters ---
        self.max_dca_levels = 6       # Allow up to 6 average-downs
        self.dca_multiplier = 1.6     # Aggressive scaling to pull avg price down fast
        self.base_dca_gap = 0.02      # 2.0% base drop required
        
        # --- Entry Parameters (Strict) ---
        self.lookback = 30
        self.entry_z_score = -3.2     # Deep statistical deviation required
        self.entry_rsi = 25.0         # Deep oversold condition
        
        # --- Exit Parameters (Profit Only) ---
        self.min_roi = 0.008          # 0.8% min profit
        self.target_roi = 0.03        # 3.0% target profit
        
        # --- State ---
        self.positions = {}           # symbol -> {'avg_price', 'quantity', 'dca_count', 'last_price'}
        self.history = {}             # symbol -> deque([prices])

    def _get_indicators(self, data):
        """Calculates Z-Score, RSI, and Volatility."""
        if len(data) < self.lookback:
            return None
            
        window = list(data)[-self.lookback:]
        current_price = window[-1]
        
        # Basic Stats
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        if stdev == 0: return None
        
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean # Coefficient of Variation
        
        # RSI (Simple 14-period approximation for speed)
        deltas = [window[i] - window[i-1] for i in range(1, len(window))]
        if len(deltas) < 14: return None
        
        recent_deltas = deltas[-14:]
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d < 0]
        
        avg_gain = sum(gains) / 14.0
        avg_loss = sum(losses) / 14.0
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility
        }

    def on_price_update(self, prices):
        """
        Decision Loop:
        1. Update Indicators
        2. SELL (Take Profit Only)
        3. DCA (Defend Position)
        4. BUY (New Entry)
        """
        
        # 1. Update Market Data
        market_state = {}
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback + 5)
            self.history[symbol].append(price)
            
            inds = self._get_indicators(self.history[symbol])
            if inds:
                market_state[symbol] = inds

        # 2. Check Exits (Priority: Secure Profits)
        # CRITICAL: We iterate positions to check for profit.
        # We explicitly skip any logic if ROI is negative (No Stop Loss).
        for symbol, pos in list(self.positions.items()):
            current_price = prices[symbol]
            avg_price = pos['avg_price']
            qty = pos['quantity']
            
            roi = (current_price - avg_price) / avg_price
            
            # --- IRON HAND LOGIC ---
            if roi <= 0:
                continue # Never sell at loss
                
            should_sell = False
            reason = []
            
            # Standard Take Profit
            if roi >= self.target_roi:
                should_sell = True
                reason = ['TP_TARGET', f"{roi:.2%}"]
            
            # Volatility Scalp: If RSI is high and we have min profit, take it
            elif roi >= self.min_roi and symbol in market_state:
                if market_state[symbol]['rsi'] > 70:
                    should_sell = True
                    reason = ['TP_RSI_PEAK', f"{roi:.2%}"]
            
            if should_sell:
                self.balance += current_price * qty
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': reason
                }

        # 3. Check DCA (Priority: Defend)
        for symbol, pos in self.positions.items():
            if pos['dca_count'] >= self.max_dca_levels:
                continue
            
            current_price = prices[symbol]
            last_price = pos['last_price']
            
            # Mutation: Dynamic Gap
            # If volatility is high, we demand a larger drop before buying again.
            # This prevents "catching a falling knife" too frequently.
            vol = market_state[symbol]['vol'] if symbol in market_state else 0.0
            required_drop = self.base_dca_gap * (1.0 + (vol * 15.0))
            
            current_drop = (last_price - current_price) / last_price
            
            if current_drop > required_drop:
                # Calculate Martingale Amount
                next_bet = self.base_bet * (self.dca_multiplier ** (pos['dca_count'] + 1))
                
                if self.balance >= next_bet:
                    amount = next_bet / current_price
                    
                    # Update Position State
                    total_cost = (pos['avg_price'] * pos['quantity']) + next_bet
                    new_qty = pos['quantity'] + amount
                    
                    pos['avg_price'] = total_cost / new_qty
                    pos['quantity'] = new_qty
                    pos['dca_count'] += 1
                    pos['last_price'] = current_price
                    
                    self.balance -= next_bet
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['DCA_DEFEND', f"Level_{pos['dca_count']}"]
                    }

        # 4. Check New Entries (Priority: Lowest)
        if len(self.positions) < self.max_positions and self.balance > self.base_bet:
            candidates = []
            for symbol, inds in market_state.items():
                if symbol in self.positions: continue
                
                # Strict Entry Logic
                if inds['z'] < self.entry_z_score and inds['rsi'] < self.entry_rsi:
                    candidates.append((symbol, inds['z']))
            
            if candidates:
                # Pick the most undervalued (lowest Z)
                candidates.sort(key=lambda x: x[1])
                best_symbol = candidates[0][0]
                price = prices[best_symbol]
                
                amount = self.base_bet / price
                
                self.positions[best_symbol] = {
                    'avg_price': price,
                    'quantity': amount,
                    'dca_count': 0,
                    'last_price': price
                }
                
                self.balance -= self.base_bet
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['ENTRY', f"Z_{candidates[0][1]:.2f}"]
                }

        return None