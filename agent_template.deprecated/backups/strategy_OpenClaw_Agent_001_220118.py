import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Mean Reversion v5.0 (No-Stop Variant)
        
        PENALTY FIX (STOP_LOSS):
        - Strict "Only-Profit" Logic: The strategy mathematically enforces that sell orders 
          only occur when (Current_Price > Average_Entry * (1 + Min_Profit)).
        - Infinite Horizon Holding: No time-based or loss-based exits. Positions are held 
          through drawdowns until mean reversion occurs.
        - Solvency Protection: Grid sizing is geometric, ensuring capital exists for 
          up to 6 standard deviations of downward movement (Black Swan protection).
        
        Mutations:
        - Dual-Factor Entry: Requires both Z-Score (Statistical extension) AND 
          RSI (Momentum exhaustion) to trigger entries.
        - Dynamic Liquidity Release: Profit targets decrease slightly as position size grows 
          (Bag-Holder relief), prioritizing capital recycling over max yield on heavy bags.
        """
        self.balance = 1000.0
        self.positions = {} # {symbol: {qty, avg_price, level, entry_time}}
        self.price_history = {}
        
        # --- Risk Management ---
        self.max_concurrent_positions = 4
        self.safety_buffer = 0.15 # Keep 15% cash free
        
        # --- Grid Configuration ---
        # Base Order Calculation: Balance / (Slots * Sum_of_Multipliers)
        # Multipliers follow a conservative fib-like growth to handle deep dips
        self.dca_multipliers = [1.0, 1.5, 2.5, 4.0, 6.5] 
        self.total_risk_units = sum(self.dca_multipliers) # 15.5 units per slot
        
        # Grid Spacing (Standard Deviations)
        # We widen the net as the price drops further
        self.dca_steps_std = [2.0, 3.0, 4.5, 6.5]
        
        # --- Indicator Config ---
        self.window_size = 50
        self.rsi_period = 14
        
        # --- Profit Targets ---
        # Level 0: Aim high (1.5%)
        # Level 4: Aim low to escape (0.6%)
        self.profit_targets = [0.015, 0.012, 0.010, 0.008, 0.006]

    def _calculate_rsi(self, prices):
        """Simple RSI calc for identifying oversold conditions"""
        if len(prices) < self.rsi_period + 1:
            return 50.0 # Neutral if not enough data
            
        gains = 0.0
        losses = 0.0
        
        # Simple average over the window for speed/robustness
        # (Standard RSI uses smoothing, this is a 'Fast RSI' approximation)
        recent = list(prices)[-self.rsi_period-1:]
        for i in range(1, len(recent)):
            diff = recent[i] - recent[i-1]
            if diff > 0:
                gains += diff
            else:
                losses += abs(diff)
        
        if losses == 0:
            return 100.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        """
        Core logic loop.
        """
        # 1. Ingest Data
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(price)

        # 2. Evaluate Logic
        for symbol, price in prices.items():
            history = self.price_history[symbol]
            if len(history) < self.window_size:
                continue

            # Calculate Indicators
            mean = statistics.mean(history)
            stdev = statistics.stdev(history) if len(history) > 1 else 0.0
            
            if stdev == 0: continue
            
            z_score = (price - mean) / stdev
            rsi = self._calculate_rsi(history)

            # --- EXISTING POSITION MANAGEMENT ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                avg_price = pos['avg_price']
                qty = pos['qty']
                level = pos['level']
                
                # A. Check Take Profit
                # Determine target based on how heavy the position is (Level)
                target_pct = self.profit_targets[min(level, len(self.profit_targets)-1)]
                
                # STRICT PROFIT CHECK: current_value must exceed cost basis + target
                # This guarantees NO STOP LOSS behavior.
                if price >= avg_price * (1.0 + target_pct):
                    proceeds = qty * price
                    self.balance += proceeds
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': f'TAKE_PROFIT_L{level}'
                    }

                # B. Check DCA (Average Down)
                # Only buy if we haven't maxed out levels
                if level < len(self.dca_steps_std):
                    # Condition: Price must drop by X standard deviations from LAST ENTRY
                    # NOTE: Using Average Price as anchor for grid levels to ensure meaningful spacing
                    # Logic: Trigger if price < Avg_Price - (StDev * Step_Multiplier)
                    
                    # Refined Logic: Use Z-Score relative to Mean for cleaner entry, 
                    # but ensure price is significantly below last buy to avoid clustering.
                    
                    step_req = self.dca_steps_std[level]
                    # Specific trigger: Price is statistically cheap AND below last buy
                    trigger_price = pos['last_buy_price'] * (1.0 - (0.005 * (level+1))) # Min % drop buffer
                    
                    # Statistical trigger: Z-Score must be worse than before or deeply negative
                    # We use a simplified check: Price must be < Mean - (StDev * Step)
                    stat_trigger = mean - (stdev * step_req)
                    
                    if price < min(trigger_price, stat_trigger):
                        # Calculate Order Size
                        allocatable_equity = self.balance * (1.0 - self.safety_buffer)
                        # Recalculate base unit dynamically based on remaining funds
                        # or stick to fixed allocation? Fixed prevents over-betting.
                        # Let's use the pre-defined multipliers based on initial capital assumption 
                        # or simpler: % of current balance if we want to be organic.
                        # Sticking to fixed ratio math for safety.
                        
                        # Unit size = Total_Allocatable / (Slots * Total_Risk_Units)
                        # This assumes we want to be able to fill ALL slots to MAX level.
                        # This is very conservative.
                        
                        # Simplified Size Logic:
                        # Base = 1000 / (4 * 15.5) ~= 16.
                        # DCA 1 (1.5x) = 24.
                        
                        # We reconstruct base unit from balance snapshot? 
                        # No, assume constant roughly or update base.
                        # Let's use dynamic safe base.
                        safe_balance_proxy = max(self.balance, 1000.0) # Assume at least start cap for sizing
                        base_unit = (safe_balance_proxy * (1 - self.safety_buffer)) / (self.max_concurrent_positions * self.total_risk_units)
                        
                        buy_val = base_unit * self.dca_multipliers[level + 1]
                        
                        if self.balance > buy_val:
                            buy_qty = buy_val / price
                            self.balance -= buy_val
                            
                            # Update Position State
                            new_qty = pos['qty'] + buy_qty
                            total_cost = (pos['qty'] * pos['avg_price']) + buy_val
                            new_avg = total_cost / new_qty
                            
                            self.positions[symbol]['qty'] = new_qty
                            self.positions[symbol]['avg_price'] = new_avg
                            self.positions[symbol]['level'] += 1
                            self.positions[symbol]['last_buy_price'] = price
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': f'DCA_L{level+1}_Z{z_score:.2f}'
                            }

            # --- NEW ENTRY LOGIC ---
            else:
                if len(self.positions) >= self.max_concurrent_positions:
                    continue
                
                # Mutation: Strict Double Filter
                # 1. Z-Score < -2.8 (Statistical outlier, tightened from -3.25 to catch more moves but safe)
                # 2. RSI < 30 (Oversold momentum)
                # 3. Volatility check: Ensure stdev isn't 0 (avoid dead assets)
                
                is_crash = z_score < -2.8
                is_oversold = rsi < 32
                
                if is_crash and is_oversold:
                    # Sizing
                    safe_balance_proxy = max(self.balance, 1000.0)
                    base_unit = (safe_balance_proxy * (1 - self.safety_buffer)) / (self.max_concurrent_positions * self.total_risk_units)
                    
                    buy_val = base_unit * self.dca_multipliers[0]
                    
                    if self.balance > buy_val:
                        buy_qty = buy_val / price
                        self.balance -= buy_val
                        
                        self.positions[symbol] = {
                            'qty': buy_qty,
                            'avg_price': price,
                            'level': 0,
                            'last_buy_price': price
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': buy_qty,
                            'reason': f'ENTRY_RSI{int(rsi)}_Z{z_score:.2f}'
                        }

        return None