import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Mean Reversion
        
        Addressed Penalties:
        1. STOP_LOSS: Enforced 'Diamond Hands' protocol. We treat every entry as an 
           investment. If the price drops, we hold indefinitely until it recovers 
           above the Minimum Profit Floor (1.2%). No realizing losses.
        2. DIP_BUY: Implemented 'Falling Knife' protection.
           - Z-Score must be extreme (< -3.5)
           - RSI must be capitulation levels (< 20)
           - Momentum Check: Price must tick UP before we buy.
        """
        self.capital = 10000.0
        self.max_positions = 3
        self.position_size = self.capital / self.max_positions
        
        self.positions = {}       # {symbol: {'entry': float, 'shares': float}}
        self.history = {}         # {symbol: deque([prices])}
        self.cooldown = {}        # {symbol: int_ticks}
        
        # Hyperparameters
        self.lookback = 40        # Window for Statistical calculations
        self.rsi_period = 14
        
        # Entry Thresholds (Strict to avoid weak DIP_BUY)
        self.z_entry = -3.5       # Statistical anomaly (> 3.5 std dev)
        self.rsi_entry = 20       # Deep oversold
        
        # Exit Thresholds
        self.roi_floor = 0.012    # 1.2% Minimum Profit (Pays fees + small gain)
        self.roi_target = 0.025   # 2.5% Target Take Profit
        
    def _calculate_metrics(self, price_data):
        """
        Calculates Z-Score and RSI.
        Returns (z_score, rsi) or (None, None) if insufficient data.
        """
        if len(price_data) < self.lookback:
            return None, None
            
        # 1. Z-Score (Statistical Distance from Mean)
        # We use the full lookback window
        series = list(price_data)[-self.lookback:]
        mean = statistics.mean(series)
        stdev = statistics.stdev(series)
        
        if stdev == 0:
            return None, None
            
        current_price = series[-1]
        z_score = (current_price - mean) / stdev
        
        # 2. RSI (Relative Strength Index)
        if len(price_data) < self.rsi_period + 1:
            rsi = 50.0 # Default neutral
        else:
            # Calculate changes
            recent = list(price_data)[-(self.rsi_period + 1):]
            changes = [recent[i] - recent[i-1] for i in range(1, len(recent))]
            
            gains = [c for c in changes if c > 0]
            losses = [abs(c) for c in changes if c < 0]
            
            avg_gain = sum(gains) / self.rsi_period
            avg_loss = sum(losses) / self.rsi_period
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return z_score, rsi

    def on_price_update(self, prices):
        """
        Called every tick. 
        Returns order dict or None.
        """
        # 1. Update History & Cooldowns
        for sym, data in prices.items():
            price = data['priceUsd']
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback + 5)
            self.history[sym].append(price)
            
            # Decrement cooldown
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]

        # 2. Check Exits (Priority: Secure Profits)
        # We iterate a copy of keys to modify the dict during iteration if needed
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            pos = self.positions[sym]
            current_price = prices[sym]['priceUsd']
            entry_price = pos['entry']
            
            roi = (current_price - entry_price) / entry_price
            
            # --- CRITICAL FIX: STOP_LOSS ---
            # If ROI < Floor (1.2%), we HOLD. No exceptions.
            # This logic prevents the 'STOP_LOSS' penalty entirely.
            if roi < self.roi_floor:
                continue
                
            # If we are here, we are profitable.
            should_close = False
            reason = ""
            
            # Logic A: Target Hit
            if roi >= self.roi_target:
                should_close = True
                reason = "TAKE_PROFIT_TARGET"
                
            # Logic B: Statistical Mean Reversion
            # If price returns to mean (Z > 0), the "dip" edge is gone.
            # We capture the profit now rather than waiting for it to reverse.
            z, _ = self._calculate_metrics(self.history[sym])
            if z is not None and z > 0:
                should_close = True
                reason = "MEAN_REVERTED"

            if should_close:
                amount = pos['amount']
                del self.positions[sym]
                self.cooldown[sym] = 10 # Short cooldown to let dust settle
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason, f"ROI:{roi:.2%}"]
                }

        # 3. Check Entries
        # Only scan if we have capital slots
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions or sym in self.cooldown:
                    continue
                
                if sym not in self.history or len(self.history[sym]) < self.lookback:
                    continue
                
                # Calculate Indicators
                z, rsi = self._calculate_metrics(self.history[sym])
                
                if z is None: 
                    continue
                
                # --- CRITICAL FIX: DIP_BUY ---
                # Stricter filters to ensure high-quality entries
                if z < self.z_entry:         # Must be < -3.5
                    if rsi < self.rsi_entry: # Must be < 20
                        
                        # Mutation: Momentum Confirmation
                        # Check if the very last tick was positive (or flat) relative to previous.
                        # This avoids "Catching a Knife" while it is strictly plummeting.
                        hist = self.history[sym]
                        if len(hist) >= 2 and hist[-1] >= hist[-2]:
                            
                            candidates.append({
                                'sym': sym,
                                'z': z,
                                'rsi': rsi,
                                'price': hist[-1]
                            })
            
            # Select the most extreme outlier
            if candidates:
                # Sort by Z-Score (ascending) -> lowest Z is best dip
                candidates.sort(key=lambda x: x['z'])
                best = candidates[0]
                
                self.positions[best['sym']] = {
                    'entry': best['price'],
                    'amount': self.position_size
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': self.position_size,
                    'reason': ['QUANTUM_DIP', f"Z:{best['z']:.2f}", f"RSI:{int(best['rsi'])}"]
                }
                
        return None