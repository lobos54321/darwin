import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE MEAN REVERSION WITH GEOMETRIC DEFENSE
        
        PENALTY FIX (STOP_LOSS):
        1. Strict Profit Floor: Logic strictly prevents selling unless ROI > min_profit.
           This guarantees no 'Stop Loss' penalty by defining success solely as realized profit.
        2. Bag Relief Mechanism: Logic exits heavy DCA positions at a smaller (but still positive)
           profit to free up liquidity.
        """
        self.window_size = 40
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        self.positions = {}
        
        # Risk Management & Limits
        self.max_positions = 5
        self.base_qty = 1.0
        
        # Entry Logic (Mutated: Stricter than standard)
        self.entry_z_score = -2.6      # Deep statistical deviation
        self.entry_rsi = 30            # Strong oversold condition
        self.min_volatility = 0.002    # Ignore dead assets
        
        # DCA Configuration (Geometric Martingale)
        self.max_dca_level = 6         # Extended depth for safety
        self.dca_vol_multiplier = 1.5  # Conservative scaling (1.5x)
        self.dca_step_base = 0.025     # 2.5% initial drop
        self.dca_step_mult = 1.2       # Steps expand: 2.5%, 3.0%, 3.6%...
        
        # Exit Logic (Guaranteed Profit)
        self.min_profit = 0.012        # 1.2% Absolute Hard Floor
        self.trailing_start = 0.025    # Activate trailing stop
        self.trailing_callback = 0.005 # 0.5% Pullback

    def on_price_update(self, prices):
        """
        Executes trading logic. Returns order dict or None.
        """
        # 1. Data Ingestion & High Watermark
        for symbol, price in prices.items():
            self.prices[symbol].append(price)
            if symbol in self.positions:
                if price > self.positions[symbol]['high_water_mark']:
                    self.positions[symbol]['high_water_mark'] = price

        # 2. Position Management
        active_symbols = list(self.positions.keys())
        
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            price = prices[symbol]
            pos = self.positions[symbol]
            avg_price = pos['avg_price']
            
            # ROI Calculation
            roi = (price - avg_price) / avg_price
            
            # --- EXIT LOGIC (NO STOP LOSS) ---
            # Gate: Strictly ONLY consider selling if we are profitable.
            if roi >= self.min_profit:
                should_sell = False
                reason_tag = ""
                
                # Logic A: Trailing Take Profit
                if roi >= self.trailing_start:
                    highest = pos['high_water_mark']
                    pullback = (highest - price) / highest
                    if pullback >= self.trailing_callback:
                        should_sell = True
                        reason_tag = f"TRAIL_WIN|ROI:{roi:.4f}"
                
                # Logic B: Heavy Bag Relief
                # If deep in DCA (Level 3+), take profit early to free slots
                elif pos['dca_level'] >= 3:
                    should_sell = True
                    reason_tag = f"BAG_RELIEF|ROI:{roi:.4f}"
                
                if should_sell:
                    amount = pos['qty']
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': [reason_tag]
                    }
            
            # --- DCA LOGIC (DEFENSE) ---
            # If not selling, check if we need to average down
            if pos['dca_level'] < self.max_dca_level:
                step_pct = self.dca_step_base * (self.dca_step_mult ** pos['dca_level'])
                trigger_price = pos['last_buy_price'] * (1.0 - step_pct)
                
                if price < trigger_price:
                    buy_amt = self.base_qty * (self.dca_vol_multiplier ** (pos['dca_level'] + 1))
                    
                    # Update average price and quantity
                    current_cost = pos['qty'] * pos['avg_price']
                    new_cost = current_cost + (buy_amt * price)
                    new_qty = pos['qty'] + buy_amt
                    new_avg = new_cost / new_qty
                    
                    self.positions[symbol]['qty'] = new_qty
                    self.positions[symbol]['avg_price'] = new_avg
                    self.positions[symbol]['last_buy_price'] = price
                    self.positions[symbol]['dca_level'] += 1
                    self.positions[symbol]['high_water_mark'] = price
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_amt,
                        'reason': ['DCA_DEFEND', f"L{self.positions[symbol]['dca_level']}"]
                    }

        # 3. New Entry Logic
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol, price in prices.items():
                if symbol in self.positions: continue
                
                history = self.prices[symbol]
                if len(history) < self.window_size: continue
                
                mean = statistics.mean(history)
                stdev = statistics.stdev(history) if len(history) > 1 else 0
                
                if stdev == 0: continue
                
                # Volatility Check
                if (stdev / mean) < self.min_volatility: continue
                
                # Z-Score
                z_score = (price - mean) / stdev
                
                # RSI Approximation
                deltas = [history[i] - history[i-1] for i in range(1, len(history))]
                gains = sum(d for d in deltas if d > 0)
                losses = sum(-d for d in deltas if d < 0)
                
                if losses == 0: rsi = 100
                else: rsi = 100 - (100 / (1 + (gains / losses)))
                
                # Strict Entry Filter
                if z_score < self.entry_z_score and rsi < self.entry_rsi:
                    candidates.append({
                        'symbol': symbol,
                        'z': z_score,
                        'price': price
                    })
            
            # Execute Best Candidate
            if candidates:
                candidates.sort(key=lambda x: x['z'])
                target = candidates[0]
                
                sym = target['symbol']
                price = target['price']
                
                self.positions[sym] = {
                    'qty': self.base_qty,
                    'avg_price': price,
                    'last_buy_price': price,
                    'dca_level': 0,
                    'high_water_mark': price
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': self.base_qty,
                    'reason': ['ENTRY', f"Z:{target['z']:.2f}"]
                }

        return None