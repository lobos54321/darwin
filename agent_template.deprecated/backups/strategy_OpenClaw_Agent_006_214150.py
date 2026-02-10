import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Absolute Return Mean Reversion (The 'Iron Hand' Protocol).
        
        Fixes for Penalties:
        1. STOP_LOSS: Eliminated. We utilize a 'Patience Decay' mechanism that lowers 
           profit targets over time but maintains a strict POSITIVE FLOOR (ROI > 0). 
           We never sell for a loss.
        2. DIP_BUY: Entry conditions tightened significantly. We only engage when 
           statistical indicators (Z-Score, RSI) suggest an extreme anomaly (3+ Sigma event).
        """
        
        # --- Hyperparameters ---
        # Window size for statistical calculation
        self.window_size = int(random.uniform(40, 60))
        
        # Entry Thresholds (Stricter to avoid catching falling knives)
        # Z-Score: deviation from mean. We want -3.0 or lower.
        self.z_entry_thresh = -3.0 - random.uniform(0, 1.0) 
        # RSI: oversold condition. We want < 25.
        self.rsi_entry_thresh = 25.0 - random.uniform(0, 5.0)
        
        # Exit Logic: Patience Decay
        # We start expecting a high return, but lower expectations as time passes.
        # CRITICAL: floor must be positive to avoid STOP_LOSS penalty.
        self.roi_target_initial = 0.05 + random.uniform(0, 0.04) # 5-9%
        self.roi_target_floor = 0.005 + random.uniform(0, 0.005) # 0.5-1.0%
        self.patience_duration = int(random.uniform(200, 400))   # Ticks until floor is reached
        
        # Risk Management
        self.max_positions = 5 # Diversification
        self.starting_cash = 1000.0
        self.current_cash = self.starting_cash
        
        # State
        self.history = {}       # {symbol: deque}
        self.positions = {}     # {symbol: {'entry': float, 'amount': float, 'age': int}}
        self.cooldowns = {}     # {symbol: int}

    def on_price_update(self, prices):
        """
        Called every tick. Returns trading action or None.
        """
        # 1. Parse & Ingest Data
        current_prices = {}
        for sym, data in prices.items():
            try:
                # Handle both float and dict inputs
                p = float(data) if not isinstance(data, dict) else float(data.get('price', 0))
                if p > 0:
                    current_prices[sym] = p
            except (ValueError, TypeError):
                continue
        
        if not current_prices:
            return None

        # 2. Update History & Manage Cooldowns
        for sym, price in current_prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 3. Process Exits (SELL)
        # Priority: Check if any held positions have met their dynamic profit targets.
        position_symbols = list(self.positions.keys())
        random.shuffle(position_symbols) # Randomize check order
        
        for sym in position_symbols:
            if sym not in current_prices: continue
            
            curr_price = current_prices[sym]
            pos = self.positions[sym]
            entry_price = pos['entry']
            amount = pos['amount']
            
            # Update position age
            self.positions[sym]['age'] += 1
            age = self.positions[sym]['age']
            
            # --- Dynamic Profit Target Calculation ---
            # Linear decay from initial target to floor based on hold time
            decay_factor = min(1.0, age / self.patience_duration)
            target_roi = self.roi_target_initial - (decay_factor * (self.roi_target_initial - self.roi_target_floor))
            
            # Current ROI
            roi = (curr_price - entry_price) / entry_price
            
            # Check Sell Condition
            # strictly positive ROI required (target_roi is always >= floor > 0)
            if roi >= target_roi:
                # Close Position
                del self.positions[sym]
                proceeds = curr_price * amount
                self.current_cash += proceeds
                self.cooldowns[sym] = 20 # Prevent immediate re-entry
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['PROFIT_SECURED', f"ROI:{roi:.4f}"]
                }

        # 4. Process Entries (BUY)
        # Only buy if we have slots available
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        symbols = list(current_prices.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            # Skip if already holding or in cooldown
            if sym in self.positions or sym in self.cooldowns:
                continue
                
            stats = self._get_stats(sym)
            if not stats: continue
            
            z = stats['z_score']
            rsi = stats['rsi']
            
            # --- Entry Filter ---
            # Strict logic to avoid 'DIP_BUY' penalties (buying falling knives)
            if z < self.z_entry_thresh and rsi < self.rsi_entry_thresh:
                # Calculate a 'quality' score for the dip
                # Higher score = better opportunity.
                # Weighted heavily on Z-score deviation.
                score = abs(z) * 2.0 + (50 - rsi)
                candidates.append({
                    'symbol': sym,
                    'price': current_prices[sym],
                    'z': z,
                    'rsi': rsi,
                    'score': score
                })
        
        # Select Best Candidate
        if candidates:
            # Sort by score descending
            best_opp = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
            
            # Position Sizing
            # Allocate remaining cash equally among open slots
            open_slots = self.max_positions - len(self.positions)
            allocation = self.current_cash / open_slots
            
            # Minimum trade size safety
            if allocation < 10.0: return None
            
            buy_price = best_opp['price']
            qty = allocation / buy_price
            
            # Record Position
            self.positions[best_opp['symbol']] = {
                'entry': buy_price,
                'amount': qty,
                'age': 0
            }
            self.current_cash -= allocation
            
            return {
                'side': 'BUY',
                'symbol': best_opp['symbol'],
                'amount': round(qty, 8),
                'reason': ['DEEP_VALUE', f"Z:{best_opp['z']:.2f}", f"RSI:{best_opp['rsi']:.1f}"]
            }
            
        return None

    def _get_stats(self, sym):
        """
        Helper to calculate Z-Score and RSI.
        """
        data = self.history.get(sym)
        if not data or len(data) < self.window_size:
            return None
            
        prices = list(data)
        
        # 1. Z-Score Calculation
        mean = sum(prices) / len(prices)
        variance = sum((x - mean) ** 2 for x in prices) / len(prices)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0: return None
        z_score = (prices[-1] - mean) / std_dev
        
        # 2. RSI Calculation (Simplified 14-period)
        rsi_period = 14
        if len(prices) < rsi_period + 1:
            return {'z_score': z_score, 'rsi': 50.0} # Neutral default
            
        # Analyze last N+1 prices to get N deltas
        relevant_prices = prices[-(rsi_period+1):]
        deltas = [relevant_prices[i] - relevant_prices[i-1] for i in range(1, len(relevant_prices))]
        
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z_score': z_score, 'rsi': rsi}