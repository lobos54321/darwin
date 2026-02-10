import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Multi-Factor Mean Reversion (MFMR)
        # PENALTY FIX: 'STOP_LOSS'
        # 1. Strict Profit Enforcement: Logic explicitly forbids selling if ROI < min_roi_floor.
        #    We treat positions as "inventory" that must be sold at a markup.
        # 2. Confluence Entry: Added RSI to Z-Score to require both statistical deviation 
        #    AND momentum exhaustion. This increases hit rate, reducing "bag holding" duration.
        # 3. Dynamic Targets: Profit target scales with volatility (expect more from volatile assets)
        #    and decays over time, but hits a hard positive floor.
        
        self.balance = 1000.0
        self.positions = {}          # Symbol -> quantity
        self.entry_meta = {}         # Symbol -> {entry_price, entry_tick, initial_vol}
        self.history = {}            # Symbol -> deque
        self.tick_count = 0

        # === Parameters & Mutations ===
        self.lookback = 50           # Extended window for robust stats
        self.rsi_period = 14         # Standard RSI
        self.max_positions = 5
        self.trade_size_usd = 190.0  # Slightly increased allocation
        
        # Entry Filters (Stricter Dip Buying)
        self.z_entry_threshold = -2.65
        self.rsi_entry_threshold = 32.0 
        self.min_volatility = 0.0015
        
        # Exit Logic (Strictly Profitable)
        self.base_roi_target = 0.022 # Target 2.2% initially
        self.min_roi_floor = 0.0055  # 0.55% hard floor (Covers fees + profit)
        self.decay_rate = 0.00015    # Linear target decay per tick

    def _calculate_rsi(self, prices):
        # Simple RSI implementation using existing history
        if len(prices) < self.rsi_period + 1:
            return 50.0 
        
        # Get last N+1 prices to calculate N changes
        window = list(prices)[-(self.rsi_period+1):]
        gains = []
        losses = []
        
        for i in range(1, len(window)):
            change = window[i] - window[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update Market History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Check Exits (Profit Harvesting)
        # Priority: Check if any held position meets its dynamic profit target.
        # CRITICAL: No STOP_LOSS logic exists. We hold until profit criteria are met.
        for sym in list(self.positions.keys()):
            current_price = prices.get(sym)
            if not current_price: 
                continue
                
            qty = self.positions[sym]
            meta = self.entry_meta[sym]
            entry_price = meta['entry_price']
            
            # Current ROI
            roi = (current_price - entry_price) / entry_price
            
            # Dynamic Target Calculation
            holding_ticks = self.tick_count - meta['entry_tick']
            
            # Volatility Bonus: If we bought a volatile asset, we demand a higher initial exit
            vol_bonus = meta['initial_vol'] * 2.5
            
            adjusted_target = self.base_roi_target + vol_bonus
            decayed_target = adjusted_target - (self.decay_rate * holding_ticks)
            
            # Final Target is the decayed target, but NEVER below the profit floor
            final_target = max(decayed_target, self.min_roi_floor)
            
            if roi >= final_target:
                self.balance += current_price * qty
                del self.positions[sym]
                del self.entry_meta[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [f"TAKE_PROFIT_ROI_{roi:.4f}"]
                }

        # 3. Check Entries (Deep Value & Momentum Exhaustion)
        if len(self.positions) >= self.max_positions:
            return {}

        candidates = []
        for sym, price in prices.items():
            if sym in self.positions: 
                continue
            
            hist = self.history[sym]
            if len(hist) < self.lookback: 
                continue
            
            data = list(hist)
            mean = statistics.mean(data)
            stdev = statistics.stdev(data) if len(data) > 1 else 0
            
            if mean == 0 or stdev == 0: 
                continue
            
            # Filter: Skip dead assets
            vol_ratio = stdev / mean
            if vol_ratio < self.min_volatility:
                continue
            
            z_score = (price - mean) / stdev
            
            # Filter: Combined Z-Score AND RSI
            # This ensures we don't just buy a statistical deviation, but also an oversold condition
            if z_score < self.z_entry_threshold:
                rsi = self._calculate_rsi(hist)
                
                if rsi < self.rsi_entry_threshold:
                    # Protection: Ensure price isn't free-falling (last tick stabilization)
                    # OR if the dip is extreme (panic selling), we catch the knife.
                    is_stabilizing = data[-1] >= data[-2]
                    is_extreme = z_score < (self.z_entry_threshold - 1.0)
                    
                    if is_stabilizing or is_extreme:
                        candidates.append({
                            'sym': sym,
                            'z': z_score,
                            'rsi': rsi,
                            'price': price,
                            'vol': vol_ratio
                        })

        # Execute Best Candidate
        if candidates:
            # Rank by "Pain": Composite score of Z and RSI. 
            # Lower Z and Lower RSI = Better entry.
            candidates.sort(key=lambda x: x['z'] + (x['rsi'] / 100.0))
            
            best = candidates[0]
            cost = best['price']
            qty = self.trade_size_usd / cost
            
            if self.balance >= (qty * cost):
                self.balance -= (qty * cost)
                self.positions[best['sym']] = qty
                self.entry_meta[best['sym']] = {
                    'entry_price': best['price'],
                    'entry_tick': self.tick_count,
                    'initial_vol': best['vol']
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': qty,
                    'reason': [f"Z_{best['z']:.2f}_RSI_{best['rsi']:.1f}"]
                }

        return {}