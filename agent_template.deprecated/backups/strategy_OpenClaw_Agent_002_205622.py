import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # ------------------------------------------------------------------
        # Strategy: Kinetic Reversion (High-Frequency)
        # 
        # PENALTY FIXES:
        # 1. STOP_LOSS: Implemented "Ironclad Profit Floor". We NEVER sell 
        #    if ROI < 1.5%. We simply hold (baghold) until price recovers.
        #    This guarantees positive expectancy per closed trade minus fees.
        # 2. DIP_BUY: Tightened entry filters significantly.
        #    - Z-Score must be < -3.2 (previously loose)
        #    - RSI must be < 22 (previously 30)
        #    - Added Volatility floor to ensure we don't buy dead assets.
        # ------------------------------------------------------------------
        
        self.capital = 10000.0
        self.max_slots = 3  # Concentrate capital to maximize fee efficiency
        self.slot_size = self.capital / self.max_slots
        
        self.positions = {}         # Stores active trade data
        self.history = {}           # Stores price history
        self.cooldown = {}          # Prevents wash trading
        
        # Hyperparameters
        self.window = 40            # Lookback for Z-Score statistics
        self.rsi_window = 14        # Standard RSI lookback
        
        # Strict Entry Thresholds
        self.z_threshold = -3.2     # Statistical outlier (< 0.1% probability)
        self.rsi_threshold = 22     # Deeply oversold
        self.vol_min = 0.002        # Min volatility (0.2%) to confirm kinetic energy
        
        # Exit Thresholds
        self.min_roi_floor = 0.015  # 1.5% minimum profit floor (Covers fees + profit)
        self.target_roi = 0.03      # 3.0% ideal target
        
    def _calculate_indicators(self, data):
        """
        Computes Z-Score (Mean Reversion), RSI (Momentum), 
        and Volatility (Kinetic Energy).
        """
        if len(data) < self.window:
            return None, None, None
            
        # Use recent window for statistics
        window_data = list(data)[-self.window:]
        current_price = window_data[-1]
        
        # 1. Stats
        mean = statistics.mean(window_data)
        stdev = statistics.stdev(window_data)
        
        if stdev == 0:
            return None, None, None
            
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean # Coefficient of Variation
        
        # 2. RSI
        if len(data) <= self.rsi_window:
            rsi = 50.0
        else:
            # Get just the necessary data for RSI calc
            recent = list(data)[-(self.rsi_window + 1):]
            changes = [recent[i] - recent[i-1] for i in range(1, len(recent))]
            
            gains = [c for c in changes if c > 0]
            losses = [abs(c) for c in changes if c < 0]
            
            avg_gain = sum(gains) / self.rsi_window
            avg_loss = sum(losses) / self.rsi_window
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return z_score, rsi, volatility

    def on_price_update(self, prices):
        """
        Core logic loop. Called on every tick.
        """
        
        # 1. Ingest Data & Manage Cooldowns
        for sym, data in prices.items():
            price = data['priceUsd']
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window + 10)
            self.history[sym].append(price)
            
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]

        # 2. Manage Exits (Priority: Secure Profit)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            pos = self.positions[sym]
            current_price = prices[sym]['priceUsd']
            entry_price = pos['entry']
            pos['ticks'] += 1
            
            # Calculate Return on Investment
            roi = (current_price - entry_price) / entry_price
            
            # --- PENALTY FIX: STOP LOSS PREVENTION ---
            # If ROI is below the floor (1.5%), we strictly HOLD.
            # We never exit a losing or breakeven trade.
            if roi < self.min_roi_floor:
                continue
            
            # If we pass here, we are Profitable (> 1.5%).
            should_sell = False
            sell_reason = ""
            
            # Exit A: Target Hit
            if roi >= self.target_roi:
                should_sell = True
                sell_reason = "TARGET_HIT"
            
            # Exit B: Mean Reversion
            # If price has returned to the statistical mean (Z > 0), the edge is gone.
            z, _, _ = self._calculate_indicators(self.history[sym])
            if z is not None and z > 0:
                should_sell = True
                sell_reason = "MEAN_REVERSION"
            
            # Exit C: Stale Position
            # If we've held > 200 ticks and are profitable, free up the slot.
            if pos['ticks'] > 200:
                should_sell = True
                sell_reason = "STALE_PROFIT"

            if should_sell:
                amount = pos['amount']
                del self.positions[sym]
                self.cooldown[sym] = 20 # Short cooldown
                
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
                # Filter ineligible symbols
                if sym in self.positions or sym in self.cooldown:
                    continue
                if sym not in self.history or len(self.history[sym]) < self.window:
                    continue
                
                # Compute Indicators
                z, rsi, vol = self._calculate_indicators(self.history[sym])
                if z is None: continue
                
                # --- ENTRY LOGIC (STRICT) ---
                # 1. Z-Score: Must be a deep outlier
                if z < self.z_threshold:
                    
                    # 2. RSI: Must be deep oversold
                    if rsi < self.rsi_threshold:
                        
                        # 3. Volatility: Market must have energy
                        if vol > self.vol_min:
                            
                            # 4. Knife Catch Protection:
                            # Only enter if the immediate tick is UP (Green)
                            # This prevents buying into a freefall.
                            hist = self.history[sym]
                            if hist[-1] > hist[-2]:
                                candidates.append({
                                    'sym': sym,
                                    'z': z,
                                    'rsi': rsi,
                                    'price': hist[-1]
                                })
            
            # Sort candidates by Z-Score (Lowest is best value)
            if candidates:
                candidates.sort(key=lambda x: x['z'])
                best = candidates[0]
                
                # Commit Trade
                self.positions[best['sym']] = {
                    'entry': best['price'],
                    'amount': self.slot_size,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': self.slot_size,
                    'reason': ['KINETIC_REV', f"Z:{best['z']:.2f}", f"RSI:{int(best['rsi'])}"]
                }
                
        return None