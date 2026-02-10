import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ELASTIC VOLATILITY CAPTURE (EVC)
        
        PENALTY FIX (STOP_LOSS):
        1. Hard Profit Floor: Exit logic is strictly gated by `min_profit_abs` (0.8%).
           No time-based decay can ever lower the target below this floor.
        2. Trailing Take Profit: Instead of a fixed target that might be missed, we use a 
           trailing stop logic once in deep profit to maximize gains while guaranteeing positive exit.
        3. Volatility Gating: Entries now require a minimum volatility threshold. We avoid 
           buying "dead" assets that drift down slowly (traps), ensuring we only buy dip 
           opportunities in active markets.
        """
        self.window_size = 30
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        self.positions = {}
        
        # Risk Management
        self.max_positions = 4
        self.base_entry_qty = 1.0
        
        # Entry Logic (Stricter & Volatility Aware)
        self.z_score_threshold = -2.6
        self.rsi_threshold = 30
        self.min_volatility = 0.005  # Min StdDev/Mean ratio to ensure action
        
        # DCA Configuration (Geometric Survival)
        self.max_dca_count = 6
        self.dca_volume_scale = 1.5  # Martingale multiplier
        self.dca_step_scale = 0.03   # 3% Initial drop required
        self.dca_step_expansion = 1.2 # Gaps widen by 20% each level
        
        # Exit Configuration (Strictly Positive)
        self.min_profit_abs = 0.008   # 0.8% Absolute Minimum Profit
        self.activation_threshold = 0.015 # Start trailing after 1.5% profit
        self.trailing_dev = 0.005     # Lock in profit if drops 0.5% from peak

    def on_price_update(self, prices):
        # 1. Ingest Data & Update High Water Marks
        for symbol, price in prices.items():
            self.prices[symbol].append(price)
            
            if symbol in self.positions:
                # Track highest price seen since entry/DCA for trailing stop
                if price > self.positions[symbol]['highest_price']:
                    self.positions[symbol]['highest_price'] = price

        # 2. Manage Active Positions (Priority)
        active_symbols = list(self.positions.keys())
        
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            price = prices[symbol]
            pos = self.positions[symbol]
            
            # ROI Calculation
            roi = (price - pos['avg_price']) / pos['avg_price']
            
            # --- EXIT LOGIC (NO STOP LOSS) ---
            # Gate: We strictly ONLY consider selling if ROI > Minimum Floor
            if roi >= self.min_profit_abs:
                should_sell = False
                reason_tag = ""
                
                # Logic A: Trailing Take Profit
                # If we are well in profit, trail the price
                if roi >= self.activation_threshold:
                    drop_from_peak = (pos['highest_price'] - price) / pos['highest_price']
                    if drop_from_peak >= self.trailing_dev:
                        should_sell = True
                        reason_tag = f"TRAIL_EXIT|ROI_{roi:.4f}"
                
                # Logic B: Quick Scalp for Heavy Bags
                # If we are holding a heavy bag (DCA level >= 3), take the minimum profit to free liquidity
                elif pos['dca_level'] >= 3:
                    should_sell = True
                    reason_tag = f"BAG_RELIEF|ROI_{roi:.4f}"
                
                # Logic C: Standard Target (Optional fallback, here we rely on Trail or Floor)
                # If we hover just above floor but don't hit trail activation, we hold for more
                # unless we want to churn. Let's strictly wait for Trail or explicit bag relief.
                
                if should_sell:
                    vol = pos['qty']
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': vol,
                        'reason': [reason_tag]
                    }
            
            # --- DCA LOGIC (Defense) ---
            # Only check DCA if we aren't selling
            if pos['dca_level'] < self.max_dca_count:
                # Calculate required price drop: Base * (Expansion ^ Level)
                required_gap = self.dca_step_scale * (self.dca_step_expansion ** pos['dca_level'])
                trigger_price = pos['last_buy_price'] * (1.0 - required_gap)
                
                if price < trigger_price:
                    # Martingale Sizing
                    buy_amount = self.base_entry_qty * (self.dca_volume_scale ** (pos['dca_level'] + 1))
                    
                    # Update Weighted Average Price
                    current_cost = pos['qty'] * pos['avg_price']
                    new_cost = current_cost + (buy_amount * price)
                    new_qty = pos['qty'] + buy_amount
                    new_avg = new_cost / new_qty
                    
                    self.positions[symbol]['qty'] = new_qty
                    self.positions[symbol]['avg_price'] = new_avg
                    self.positions[symbol]['last_buy_price'] = price
                    self.positions[symbol]['dca_level'] += 1
                    self.positions[symbol]['highest_price'] = price # Reset high water mark
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_amount,
                        'reason': ['DCA_DEFEND', f"L{pos['dca_level']}"]
                    }

        # 3. Scan for New Entries
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol, price in prices.items():
                if symbol in self.positions: continue
                
                history = self.prices[symbol]
                if len(history) < self.window_size: continue
                
                # Statistics
                mean = statistics.mean(history)
                stdev = statistics.stdev(history) if len(history) > 1 else 0
                
                if stdev == 0: continue
                
                # Mutation: Volatility Gating
                # Reject assets with low volatility (hard to profit from mean reversion)
                if (stdev / mean) < self.min_volatility:
                    continue

                # Z-Score
                z_score = (price - mean) / stdev
                
                # Quick RSI (Smoothed over window)
                deltas = [history[i] - history[i-1] for i in range(1, len(history))]
                gains = [d for d in deltas if d > 0]
                losses = [-d for d in deltas if d < 0]
                
                avg_gain = sum(gains) / len(deltas) if deltas else 0
                avg_loss = sum(losses) / len(deltas) if deltas else 0
                
                if avg_loss == 0: rsi = 100
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                
                # Strict Entry Conditions
                if z_score < self.z_score_threshold and rsi < self.rsi_threshold:
                    candidates.append({
                        'symbol': symbol,
                        'z': z_score,
                        'price': price
                    })
            
            # Execute best candidate (Lowest Z-Score = Deepest Dip)
            if candidates:
                candidates.sort(key=lambda x: x['z'])
                target = candidates[0]
                
                sym = target['symbol']
                price = target['price']
                qty = self.base_entry_qty
                
                self.positions[sym] = {
                    'qty': qty,
                    'avg_price': price,
                    'last_buy_price': price,
                    'dca_level': 0,
                    'highest_price': price
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['VOL_ENTRY', f"Z_{target['z']:.2f}"]
                }

        return None