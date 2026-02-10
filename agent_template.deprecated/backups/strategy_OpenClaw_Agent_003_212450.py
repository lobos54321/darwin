import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: DEEP VALUE SNIPER (ANTI-FRAGILE)
        
        FIX FOR 'STOP_LOSS' PENALTY:
        - The penalty implies the previous strategy exhausted capital or hit forced liquidations 
          during market crashes.
        - SOLUTION: Transitioned to 'Geometric Widening' for DCA and 'Extreme Deviation' for entries.
        
        KEY MUTATIONS:
        1. Extreme Patience Entry: Z-Score threshold lowered to -3.0 (from -2.65). 
           We only enter when the asset is statistically broken.
        2. Quadratic Grid Expansion: DCA levels expand non-linearly (Level^1.5) to survive 
           extended drawdowns without exhausting ammo.
        3. Volatility Governor: If local volatility is high (>2%), entry requirements tighten further automatically.
        4. Conservative Sizing: Reduced DCA buy multiplier to 1.3x to preserve "dry powder".
        """
        
        self.window_size = 120
        # Data storage: Symbol -> deque of recent prices
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio: Symbol -> {'avg_cost': float, 'qty': float, 'dca_lvl': int, 'held_ticks': int}
        self.portfolio = {}
        
        self.config = {
            # Risk Management
            "max_slots": 5,
            "base_amt": 1.0,
            
            # Entry Filters (EXTREME)
            "z_entry_base": -3.0,   # Requires 3 sigma deviation (99.7% prob rarity)
            "rsi_entry": 25,        # Deep oversold
            
            # DCA Survival Settings
            "max_dca_lvl": 8,           # More levels allowed
            "dca_vol_width_base": 2.2,  # Base width in StdDevs
            "dca_multiplier": 1.3,      # Slower geometric compounding (1, 1.3, 1.69...)
            
            # Exit Logic (Strict Positive ROI)
            "roi_target": 0.03,     # 3.0% Target
            "roi_floor": 0.007,     # 0.7% Hard Floor (covers fees safely)
            "roi_decay": 0.00003,   # Decay speed
        }

    def _get_stats(self, symbol):
        data = self.prices[symbol]
        if len(data) < 40:
            return None
        
        prices_list = list(data)
        curr_price = prices_list[-1]
        
        mean = statistics.mean(prices_list)
        stdev = statistics.stdev(prices_list) if len(prices_list) > 1 else 0.0
        
        if stdev == 0:
            return None
            
        z = (curr_price - mean) / stdev
        
        # RSI Calculation (14 period)
        period = 14
        if len(prices_list) <= period:
            rsi = 50.0
        else:
            changes = [prices_list[i] - prices_list[i-1] for i in range(1, len(prices_list))]
            recent = changes[-period:]
            
            gains = [c for c in recent if c > 0]
            losses = [-c for c in recent if c < 0]
            
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            'z': z,
            'std': stdev,
            'rsi': rsi,
            'price': curr_price,
            'mean': mean
        }

    def on_price_update(self, prices):
        # 1. Update Market Data
        for sym, price in prices.items():
            self.prices[sym].append(price)
            
        # 2. Manage Existing Positions
        # Check Exits (TP) and DCA triggers
        active_symbols = sorted(
            self.portfolio.keys(),
            key=lambda s: (prices[s] - self.portfolio[s]['avg_cost']) / self.portfolio[s]['avg_cost'],
            reverse=True
        )

        for sym in active_symbols:
            pos = self.portfolio[sym]
            curr_price = prices[sym]
            pos['held_ticks'] += 1
            
            cost = pos['avg_cost']
            qty = pos['qty']
            roi = (curr_price - cost) / cost
            
            # Dynamic Profit Target
            target_roi = max(
                self.config["roi_floor"],
                self.config["roi_target"] - (pos['held_ticks'] * self.config["roi_decay"])
            )
            
            # EXIT CHECK
            if roi >= target_roi:
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TP_SNIPER', f'ROI_{roi:.4f}']
                }
            
            # RECOVERY CHECK (DCA)
            if roi < 0 and pos['dca_lvl'] < self.config["max_dca_lvl"]:
                stats = self._get_stats(sym)
                if stats:
                    # Adaptive Grid: Widens as we go deeper (Quadratic expansion)
                    # Prevents buying too frequently in a crash
                    level_expansion = 1.0 + (0.4 * (pos['dca_lvl'] ** 1.5))
                    required_drop = stats['std'] * self.config["dca_vol_width_base"] * level_expansion
                    
                    trigger_price = cost - required_drop
                    
                    if curr_price < trigger_price:
                        # Geometric Sizing
                        buy_amt = self.config["base_amt"] * (self.config["dca_multiplier"] ** (pos['dca_lvl'] + 1))
                        
                        # Virtual Execution
                        new_qty = qty + buy_amt
                        new_cost = ((qty * cost) + (buy_amt * curr_price)) / new_qty
                        
                        pos['qty'] = new_qty
                        pos['avg_cost'] = new_cost
                        pos['dca_lvl'] += 1
                        pos['held_ticks'] = 0 
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_amt,
                            'reason': ['DCA_RECOVERY', f'LVL_{pos["dca_lvl"]}']
                        }

        # 3. Scan for New Entries (Filtered)
        if len(self.portfolio) < self.config["max_slots"]:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.portfolio:
                    continue
                
                stats = self._get_stats(sym)
                if not stats:
                    continue
                
                # VOLATILITY GOVERNOR
                # Calculate relative volatility (std dev as % of price)
                vol_ratio = stats['std'] / stats['mean']
                
                # Base Threshold
                z_thresh = self.config["z_entry_base"]
                
                # If market is extremely volatile (>2%), require even deeper discount
                if vol_ratio > 0.02:
                    z_thresh -= 0.5 # Shifts to -3.5
                
                if stats['z'] < z_thresh and stats['rsi'] < self.config["rsi_entry"]:
                    candidates.append((sym, stats))
            
            if candidates:
                # Sort by strongest statistical signal (lowest Z)
                candidates.sort(key=lambda x: x[1]['z'])
                best_sym, best_stats = candidates[0]
                
                amt = self.config["base_amt"]
                
                self.portfolio[best_sym] = {
                    'avg_cost': best_stats['price'],
                    'qty': amt,
                    'dca_lvl': 0,
                    'held_ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': amt,
                    'reason': ['ENTRY_DEEP_VAL', f'Z_{best_stats["z"]:.2f}']
                }
                
        return None