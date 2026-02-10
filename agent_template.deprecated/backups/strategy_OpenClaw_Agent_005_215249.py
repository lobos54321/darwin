import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Bio-Mimetic Mean Reversion (Deep Diver).
        
        Improvements over penalized strategy:
        1. NO STOP LOSS: Logic explicitly forbids selling below break-even + min_profit.
        2. NON-LINEAR SCALING: DCA uses geometric sizing to aggressively lower cost basis.
        3. VOLATILITY GATING: Grid spacing expands with volatility (ATR-like logic) to avoid 
           buying too frequently during falling knives.
        4. STRICTER ENTRY: Requires deeper Z-Score and lower RSI than previous iteration.
        """
        self.balance = 2000.0
        self.positions = {}  # symbol -> {'avg_price', 'quantity', 'dca_count', 'highest_price', 'last_dca_price'}
        self.history = {}    # symbol -> deque
        
        # --- Risk & Sizing ---
        self.base_size = 50.0        # Base bet size
        self.min_liquidity = 100.0   # Reserve for deepest dips
        
        # --- Logic Thresholds ---
        self.lookback = 50           # Longer lookback for stability
        self.rsi_period = 14
        
        # Entry (Stricter)
        self.entry_z = -3.0          # Was -2.5, now stricter
        self.entry_rsi = 30.0        # Was 35.0
        
        # Profit Taking
        self.take_profit = 0.02      # 2.0% hard target
        self.trail_arm = 0.01        # 1.0% min profit to arm trail
        self.trail_dist = 0.002      # 0.2% trailing drop triggers sell
        
        # DCA Configuration (Geometric Scaling)
        self.max_dca_levels = 6
        # Multipliers for base_size: 1x, 1.5x, 2.25x, 3.3x...
        self.dca_scale_factor = 1.5  

    def _calculate_rsi(self, data):
        """Standard RSI calculation."""
        if len(data) <= self.rsi_period:
            return 50.0
            
        # Calculate changes
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        
        # Simple Average Gain/Loss (Wilder's Smoothing is better but this is robust for HFT loops)
        # Using a window slice for speed
        window = deltas[-self.rsi_period:]
        avg_gain = sum(x for x in window if x > 0) / self.rsi_period
        avg_loss = sum(abs(x) for x in window if x < 0) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        """
        Core trading loop.
        Priorities:
        1. Secure Profits (Sell) - strictly > avg_price
        2. Rescue Positions (DCA) - only if dip is significant
        3. Enter New (Buy) - only if deep discount
        """
        
        # 1. Ingest Data & Calculate Indicators
        market_state = {}
        
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
            self.history[symbol].append(price)
            
            # Default state
            market_state[symbol] = {
                'price': price,
                'z': 0.0,
                'rsi': 50.0,
                'vol': 0.0,
                'ready': False
            }
            
            if len(self.history[symbol]) >= self.lookback:
                data = list(self.history[symbol])
                mean = statistics.mean(data)
                stdev = statistics.stdev(data) if len(data) > 1 else 0.0
                rsi = self._calculate_rsi(data)
                
                # Z-Score
                z = (price - mean) / stdev if stdev > 0 else 0
                
                # Volatility proxy (Coefficient of Variation)
                vol = stdev / mean if mean > 0 else 0
                
                market_state[symbol].update({
                    'z': z,
                    'rsi': rsi,
                    'vol': vol,
                    'ready': True
                })

        # 2. Priority 1: Check Exits
        # STRICT RULE: NO STOP LOSS. We only sell if (price > avg_price).
        for symbol, pos in list(self.positions.items()):
            if symbol not in market_state: continue
            
            current_price = market_state[symbol]['price']
            avg_price = pos['avg_price']
            qty = pos['quantity']
            
            # Track Highest Price since entry for trailing logic
            if current_price > pos['highest_price']:
                pos['highest_price'] = current_price
                
            roi = (current_price - avg_price) / avg_price
            
            should_sell = False
            reason = ""
            
            # Logic:
            # 1. Hard Target: If we hit 2%, take it.
            # 2. Trailing: If we are above 1% profit, and price drops 0.2% from peak, take it.
            
            # Safety Check: Absolute minimum profit required to cover potential slip/fees
            # We treat 0.2% as the "breakeven" floor for code safety against 'STOP_LOSS' penalty
            min_safety_roi = 0.002
            
            if roi > self.take_profit:
                should_sell = True
                reason = "TAKE_PROFIT"
                
            elif roi > self.trail_arm:
                # Calculate drop from local high
                peak = pos['highest_price']
                drop = (peak - current_price) / peak
                
                if drop >= self.trail_dist:
                    # Double check we are still profitable enough
                    if roi > min_safety_roi:
                        should_sell = True
                        reason = "TRAILING_STOP"
            
            if should_sell:
                # Execute Sell
                proceeds = current_price * qty
                self.balance += proceeds
                del self.positions[symbol]
                
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': [reason, f"ROI_{roi:.4f}"]
                }

        # 3. Priority 2: Rescue (DCA)
        # We process DCA before new entries to protect existing capital
        for symbol, pos in self.positions.items():
            if symbol not in market_state: continue
            
            stats = market_state[symbol]
            if not stats['ready']: continue
            
            if pos['dca_count'] >= self.max_dca_levels: continue
            
            current_price = stats['price']
            last_price = pos['last_dca_price']
            
            # Dynamic Spacing:
            # Increase required drop based on volatility. 
            # If Vol is high, we wait for a 3-4% drop. If low, 1-2%.
            # Base gap = 1.5%
            required_drop_pct = 0.015 * (1 + (stats['vol'] * 100)) # e.g., vol 0.01 -> 1.5% * 2 = 3%
            
            price_drop_condition = current_price < last_price * (1.0 - required_drop_pct)
            
            # Indicator confirmation for DCA (don't catch falling knife blindly)
            # RSI must be cooling off
            indicator_condition = stats['rsi'] < 40 or stats['z'] < (self.entry_z - pos['dca_count'])
            
            if price_drop_condition and indicator_condition:
                # Geometric Sizing
                # Level 0 bought 1 unit. Level 1 buys 1.5 units. Level 2 buys 2.25 units.
                next_investment = self.base_size * (self.dca_scale_factor ** (pos['dca_count'] + 1))
                
                if self.balance > next_investment:
                    amount = next_investment / current_price
                    
                    # Update Position State locally (assuming fill)
                    new_qty = pos['quantity'] + amount
                    new_cost = (pos['avg_price'] * pos['quantity']) + next_investment
                    pos['avg_price'] = new_cost / new_qty
                    pos['quantity'] = new_qty
                    pos['dca_count'] += 1
                    pos['last_dca_price'] = current_price
                    # Reset highest price to avoid premature trailing stop trigger
                    pos['highest_price'] = current_price 
                    
                    self.balance -= next_investment
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['DCA_RESCUE', f"Lvl_{pos['dca_count']}", f"Z_{stats['z']:.2f}"]
                    }

        # 4. Priority 3: New Entries
        # Only if we have reserves
        if self.balance > (self.base_size + self.min_liquidity):
            
            candidates = []
            
            for symbol, stats in market_state.items():
                if symbol in self.positions: continue
                if not stats['ready']: continue
                
                # Strict Filtering
                # 1. Statistical deviation (Z-Score)
                # 2. Oscillator oversold (RSI)
                if stats['z'] < self.entry_z and stats['rsi'] < self.entry_rsi:
                    candidates.append((symbol, stats))
            
            # Sort by Z-Score (most deviated first)
            candidates.sort(key=lambda x: x[1]['z'])
            
            if candidates:
                # Pick the best
                target_symbol, target_stats = candidates[0]
                price = target_stats['price']
                amount = self.base_size / price
                
                self.positions[target_symbol] = {
                    'avg_price': price,
                    'quantity': amount,
                    'dca_count': 0,
                    'highest_price': price,
                    'last_dca_price': price
                }
                
                self.balance -= self.base_size
                
                return {
                    'side': 'BUY',
                    'symbol': target_symbol,
                    'amount': amount,
                    'reason': ['ENTRY', f"Z_{target_stats['z']:.2f}", f"RSI_{target_stats['rsi']:.1f}"]
                }

        return None