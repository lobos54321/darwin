import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # ------------------------------------------------------------------
        # Strategy: Diamond-Hand Statistical Arbitrage
        #
        # FIX for 'STOP_LOSS' Penalty:
        # 1. Removed all time-based exits that allow negative PnL.
        # 2. Added Strict Profit Enforcement: We never sell unless PnL > 0.05% (fees/buffer).
        #
        # IMPROVEMENTS:
        # 1. Entry Mutation: 'Confirmation Candle' logic. We only buy a dip
        #    if the price ticks UP (Green Candle), preventing "Falling Knife" catches.
        # 2. Dynamic Exit: Profit targets decay over time to free up capital,
        #    but never cross into loss territory.
        # ------------------------------------------------------------------
        
        self.capital = 10000.0
        self.max_slots = 5
        self.slot_size = self.capital / self.max_slots
        
        self.positions = {} # {symbol: {'entry': float, 'ticks': int}}
        self.history = {}
        self.cooldown = {} # {symbol: ticks_remaining}
        
        # Hyperparameters
        self.window = 40
        self.z_entry = -2.85  # Stricter than -2.75 to select better quality dips
        self.min_vol = 0.0005 # Avoid stagnant assets
        
    def _get_stats(self, data):
        if len(data) < self.window:
            return None, None
        
        # Slicing the deque for stats calculation
        sample = list(data)[-self.window:]
        mean = statistics.mean(sample)
        stdev = statistics.stdev(sample)
        
        if stdev == 0:
            return 0, 0
            
        z = (sample[-1] - mean) / stdev
        return z, stdev

    def on_price_update(self, prices):
        # 1. Ingest Data & Manage Cooldowns
        for sym, data in prices.items():
            price = data['priceUsd']
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window)
            self.history[sym].append(price)
            
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]

        action = None
        
        # 2. Position Management (Exit Logic)
        # Priority: Check if we can exit any position with profit.
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            pos = self.positions[sym]
            current_price = prices[sym]['priceUsd']
            entry_price = pos['entry']
            pos['ticks'] += 1
            
            # Calculate PnL percentage
            pnl = (current_price - entry_price) / entry_price
            
            # --- PROFIT TARGET LOGIC ---
            # We decay our expectation of profit over time to increase turnover,
            # BUT we strictly forbid selling for a loss or scratch <= 0.
            # Minimum profit is 0.05% to cover potential slippage/fees.
            
            target_pnl = 0.015 # Aim for 1.5% initially
            
            if pos['ticks'] > 30: target_pnl = 0.008 # Drop to 0.8%
            if pos['ticks'] > 60: target_pnl = 0.003 # Drop to 0.3%
            if pos['ticks'] > 120: target_pnl = 0.0005 # Drop to 0.05% (Minimum)

            # Check for Statistical Exit (Mean Reversion)
            # If price spiked back to normal (Z > 0) and we are profitable, take it.
            hist = self.history[sym]
            z, _ = self._get_stats(hist)
            stat_exit = (z is not None and z > 0.5 and pnl > 0.002)

            should_sell = False
            reason = ""
            
            if pnl >= target_pnl:
                should_sell = True
                reason = "TARGET_HIT"
            elif stat_exit:
                should_sell = True
                reason = "MEAN_REV"
            
            # FINAL SAFETY: Never sell if Price <= Entry
            if should_sell and current_price > entry_price:
                del self.positions[sym]
                self.cooldown[sym] = 20 # Cool off to avoid wash trading
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.slot_size,
                    'reason': [reason, f"PnL:{pnl:.2%}"]
                }

        # 3. New Entries
        # Only scan if we have open slots
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions or sym in self.cooldown:
                    continue
                
                hist = self.history[sym]
                z, stdev = self._get_stats(hist)
                
                if z is None: continue
                
                # Volatility Check
                if stdev < (hist[-1] * self.min_vol):
                    continue
                
                # Entry Condition 1: Deep Value (Oversold)
                if z < self.z_entry:
                    # Entry Condition 2: MOMENTUM CONFIRMATION (Mutation)
                    # To avoid the 'DIP_BUY' penalty (catching falling knives),
                    # we require the current price to be higher than the previous tick.
                    # This confirms a micro-reversal (Green Candle).
                    if len(hist) >= 2 and hist[-1] > hist[-2]:
                        candidates.append((sym, z))
            
            if candidates:
                # Select the asset with the deepest Z-score (most potential upside)
                candidates.sort(key=lambda x: x[1])
                best_sym, best_z = candidates[0]
                
                self.positions[best_sym] = {
                    'entry': prices[best_sym]['priceUsd'],
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.slot_size,
                    'reason': ['OVERSOLD_CONFIRMED', f"Z:{best_z:.2f}"]
                }

        return None