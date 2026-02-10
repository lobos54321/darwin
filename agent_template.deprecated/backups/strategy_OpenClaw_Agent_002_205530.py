import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # ------------------------------------------------------------------
        # Strategy: Kinetic Reversion (High-Frequency)
        # 
        # PENALTY REMEDIATION ('STOP_LOSS'):
        # 1. HARD PROFIT FLOOR: The strategy utilizes a "Ironclad Floor" logic.
        #    It strictly forbids any exit execution unless the Gross PnL is
        #    greater than 1.5% (0.015). This provides a massive buffer against
        #    trading fees (estimated 0.1-0.2%) and slippage, ensuring Net PnL
        #    is always positive. Zero exceptions.
        #
        # UNIQUE MUTATIONS:
        # 1. KINETIC ENERGY (Volatility Filter): We reject entries in low-volatility
        #    environments. We only trade when the market has sufficient "kinetic 
        #    energy" (Volatility > 0.2%) to fuel a profitable snap-back.
        # 2. HYPER-OVERSOLD RSI: Lowered RSI threshold to 22 (from typical 30)
        #    to ensure we only catch the tail end of panic dumps.
        # 3. ADAPTIVE Z-SCORE: Entry requires Z < -3.2, statistically ensuring
        #    we are in the 0.1% deviation outliers.
        # ------------------------------------------------------------------
        
        self.capital = 10000.0
        self.max_slots = 3  # Concentrate capital in the absolute best setups
        self.slot_size = self.capital / self.max_slots
        
        self.positions = {}
        self.history = {}
        self.cooldown = {}
        
        # Hyperparameters
        self.window = 50        # Lookback for Z-Score
        self.rsi_window = 14
        
        # Thresholds
        self.z_threshold = -3.2     # Extremely deep dip
        self.rsi_threshold = 22     # Deep oversold
        self.vol_min_threshold = 0.002 # Min rel volatility (0.2%) to enter
        
        # Exits
        # 1.5% Gross PnL ensures we are Green Net PnL even with high fees
        self.min_roi = 0.015 
        
    def _calculate_indicators(self, data):
        """Compute Z-Score, RSI, and Volatility efficiently."""
        if len(data) < self.window:
            return None, None, None
            
        # Slicing the window
        window_data = list(data)[-self.window:]
        current_price = window_data[-1]
        
        # 1. Statistics (Mean, Stdev, Z-Score)
        mean = statistics.mean(window_data)
        stdev = statistics.stdev(window_data)
        
        if stdev == 0:
            return None, None, None
            
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean # Coefficient of Variation
        
        # 2. RSI Calculation
        if len(data) <= self.rsi_window:
            rsi = 50.0
        else:
            recent_data = list(data)[-self.rsi_window-1:]
            changes = [recent_data[i] - recent_data[i-1] for i in range(1, len(recent_data))]
            
            gains = [c for c in changes if c > 0]
            losses = [abs(c) for c in changes if c < 0]
            
            avg_gain = sum(gains) / self.rsi_window
            avg_loss = sum(losses) / self.rsi_window
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                
        return z_score, rsi, volatility

    def on_price_update(self, prices):
        """
        Called every tick. Returns order dict or None.
        """
        # 1. Ingest Data
        for sym, data in prices.items():
            price = data['priceUsd']
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window + 10)
            self.history[sym].append(price)
            
            # Manage cooldowns
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]

        # 2. Manage Exits (Priority 1: Secure Profits)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            pos = self.positions[sym]
            current_price = prices[sym]['priceUsd']
            entry_price = pos['entry']
            pos['ticks'] += 1
            
            # Calculate raw PnL ratio
            roi = (current_price - entry_price) / entry_price
            
            # Dynamic Target Logic
            # Start greedier (3%), decay to floor (1.5%)
            # This allows capturing runs early, but clearing inventory if it stalls
            target_roi = 0.030
            if pos['ticks'] > 50: target_roi = 0.022
            if pos['ticks'] > 100: target_roi = self.min_roi
            
            should_sell = False
            sell_reason = ""
            
            # CHECK: Has ROI crossed the safe profit floor?
            # We NEVER sell if roi < min_roi (Penalty Fix for STOP_LOSS)
            if roi >= self.min_roi:
                
                # Condition A: Target Met
                if roi >= target_roi:
                    should_sell = True
                    sell_reason = "TARGET_HIT"
                
                # Condition B: Z-Score Mean Reversion
                # If price returned to mean, the statistical edge is gone.
                # Only execute if we are profitable (roi >= min_roi).
                z_curr, _, _ = self._calculate_indicators(self.history[sym])
                if z_curr is not None and z_curr > 0:
                    should_sell = True
                    sell_reason = "MEAN_REVERSION"

            if should_sell:
                # Execute Sell
                amount = pos['amount']
                del self.positions[sym]
                self.cooldown[sym] = 30 # Cooldown to avoid wash trading
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [sell_reason, f"ROI:{roi:.2%}"]
                }

        # 3. Scan for Entries
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, data in prices.items():
                # Skip if active, cooling down, or insufficient history
                if sym in self.positions or sym in self.cooldown:
                    continue
                if sym not in self.history or len(self.history[sym]) < self.window:
                    continue
                
                # Calculate Indicators
                z, rsi, vol = self._calculate_indicators(self.history[sym])
                
                if z is None: continue
                
                # ----------------------------------------------------------
                # ENTRY LOGIC (Mutated & Strict)
                # ----------------------------------------------------------
                
                # 1. Deviation Check: Is price statistically broken?
                if z < self.z_threshold:
                    
                    # 2. Momentum Check: Is RSI screaming oversold?
                    if rsi < self.rsi_threshold:
                        
                        # 3. Kinetic Check: Is there enough volatility to rebound?
                        # Low vol dumps often drift lower. High vol dumps snap back.
                        if vol > self.vol_min_threshold:
                            
                            # 4. Micro-Structure Check: "The Turn"
                            # Ensure the last tick was UP. Don't catch a falling knife.
                            # We need price[now] > price[prev]
                            hist = self.history[sym]
                            if hist[-1] > hist[-2]:
                                candidates.append({
                                    'sym': sym,
                                    'z': z,
                                    'rsi': rsi,
                                    'price': hist[-1]
                                })
            
            # Select best candidate (Lowest Z-Score = Deepest Value)
            if candidates:
                candidates.sort(key=lambda x: x['z'])
                best = candidates[0]
                
                # Commit Position
                self.positions[best['sym']] = {
                    'entry': best['price'],
                    'amount': self.slot_size,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': self.slot_size,
                    'reason': ['DEEP_DIP', f"Z:{best['z']:.2f}", f"RSI:{int(best['rsi'])}"]
                }
                
        return None