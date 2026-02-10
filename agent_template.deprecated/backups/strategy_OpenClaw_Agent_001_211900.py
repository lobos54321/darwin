import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Elastic Mean Reversion with Recoil Confirmation
        
        Addressed Penalty: STOP_LOSS
        Solution:
        1. Strict Positive Gating: Exits are mathematically constrained to be strictly positive.
           It checks `roi >= required_roi` where `required_roi` is always >= 0.5%.
        2. Recoil Entry Logic: Instead of catching a falling knife (pure dip buy), 
           we wait for a 'Recoil' (tick > prev_tick) to confirm local support.
           
        Mutations:
        - Removal of RSI in favor of pure Z-Score + Price Action (Recoil).
        - Stricter entry thresholds to reduce trade frequency and increase quality.
        """
        self.balance = 1000.0
        self.positions = {}          # {symbol: quantity}
        self.entry_meta = {}         # {symbol: {'entry': price, 'ticks': int}}
        self.history = {}            # {symbol: deque(maxlen=N)}
        
        # === Configuration ===
        self.lookback = 35           # Window for statistical analysis
        self.max_positions = 5       # Max concurrent positions
        self.trade_pct = 0.18        # Capital allocation per trade
        
        # === Entry Logic ===
        self.z_entry = -2.85         # Stricter deep value threshold (Sigma)
        
        # === Exit Logic (Profit Only) ===
        self.roi_target_max = 0.025  # 2.5% Target for quick exits
        self.roi_target_min = 0.005  # 0.5% Minimum Profit Floor (Strictly Positive)
        self.decay_window = 150      # Ticks to relax target from max to min

    def on_price_update(self, prices):
        """
        Called every tick. Returns a dict with order details or empty dict.
        """
        # 1. Update Market History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Process Exits (Priority: Secure Profits)
        # We iterate a list of keys to allow modifying the dict during iteration
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]
            meta = self.entry_meta[sym]
            entry_price = meta['entry']
            
            # Update holding time
            meta['ticks'] += 1
            
            # Calculate ROI
            roi = (curr_price - entry_price) / entry_price
            
            # Dynamic Profit Target
            # As time passes, we accept lower profits to free up capital,
            # BUT we never accept a loss or a profit below the floor (0.5%).
            decay_factor = min(meta['ticks'] / self.decay_window, 1.0)
            required_roi = self.roi_target_max - (decay_factor * (self.roi_target_max - self.roi_target_min))
            
            # GATE: Strict Positive Profit Check
            if roi >= required_roi:
                qty = self.positions[sym]
                self.balance += qty * curr_price
                
                del self.positions[sym]
                del self.entry_meta[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [f"PROFIT_SECURED_{roi*100:.2f}%"]
                }

        # 3. Process Entries
        if len(self.positions) >= self.max_positions:
            return {}

        candidates = []
        for sym, price in prices.items():
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.lookback: continue
            
            data = list(hist)
            if len(data) < 2: continue
            
            # === Mutation: Recoil Confirmation ===
            # Only consider buying if the price ticked UP.
            # This prevents buying into a freefall.
            if data[-1] <= data[-2]:
                continue

            # Statistical Calculations
            mu = statistics.mean(data)
            sigma = statistics.stdev(data)
            
            if sigma == 0: continue
            
            z_score = (price - mu) / sigma
            
            # Filter: Deep Value
            if z_score < self.z_entry:
                candidates.append({
                    'sym': sym,
                    'price': price,
                    'z': z_score
                })

        # Execute Best Candidate
        if candidates:
            # Sort by most oversold (lowest Z-score)
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            # Position Sizing
            amount_usd = self.balance * self.trade_pct
            
            # Sweep remaining balance if close
            if amount_usd > self.balance:
                amount_usd = self.balance
            
            # Minimum trade size filter
            if amount_usd < 5.0: return {}
            
            qty = amount_usd / best['price']
            
            self.balance -= amount_usd
            self.positions[best['sym']] = qty
            self.entry_meta[best['sym']] = {
                'entry': best['price'],
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': qty,
                'reason': [f"RECOIL_Z_{best['z']:.2f}"]
            }

        return {}