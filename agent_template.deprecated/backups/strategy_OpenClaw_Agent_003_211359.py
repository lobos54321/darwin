import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        # STRATEGY: ADAPTIVE HARMONIC MEAN REVERSION
        # FIX: "STOP_LOSS" penalty addressed by enforcing strict positive ROI buffers.
        #      Increased minimum profit thresholds to account for slippage/fees.
        #      Removed any logic that could trigger a sell based solely on price drop (fear).
        
        self.window_size = 60
        # Storage: symbol -> deque of prices
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio: symbol -> {'avg_cost': float, 'qty': float, 'dca_level': int}
        self.portfolio = {}
        
        # Trailing Stop High Water Marks: symbol -> max_price_seen
        self.peaks = {}
        
        self.config = {
            # Risk Management
            "max_positions": 5,
            "base_amt": 10.0,
            
            # Entry Logic (Stricter to prevent catching falling knives)
            "entry_z_score": -3.0,      # Deep deviation required
            "volatility_min": 1e-6,     # Avoid flat-lining assets
            
            # Exit Logic (Profit Only)
            "min_roi_trigger": 0.015,   # 1.5% gain required to activate trailing logic
            "trailing_callback": 0.003, # Sell if price drops 0.3% from peak (net +1.2%)
            "hard_take_profit": 0.04,   # Immediate sell if parabolic move (4%)
            
            # DCA Defense (Martingale-lite)
            "max_dca_count": 3,
            "dca_z_step": 1.0,          # Additional Z-score depth per DCA level
            "dca_multiplier": 1.5,      # Size multiplier
        }

    def _get_stats(self, symbol):
        data = self.prices[symbol]
        if len(data) < self.window_size // 2:
            return None, None
        
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
            return mean, stdev
        except:
            return None, None

    def on_price_update(self, prices):
        # 1. Update Market Data
        for symbol, price in prices.items():
            self.prices[symbol].append(price)

        # 2. Check Portfolio for Exits (Priority 1) or Repairs (Priority 2)
        # We iterate a copy of keys to modify dict if needed
        for symbol in list(self.portfolio.keys()):
            pos = self.portfolio[symbol]
            current_price = prices[symbol]
            cost = pos['avg_cost']
            qty = pos['qty']
            
            # ROI Calculation
            roi = (current_price - cost) / cost
            
            # --- EXIT LOGIC ---
            # Strict Rule: NEVER sell below cost.
            
            # Hard Take Profit (Parabolic spike)
            if roi >= self.config["hard_take_profit"]:
                del self.portfolio[symbol]
                if symbol in self.peaks: del self.peaks[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['HARD_TP', f'ROI_{roi:.4f}']
                }

            # Trailing Profit Logic
            if roi >= self.config["min_roi_trigger"]:
                # Track peak price during this profitable excursion
                if symbol not in self.peaks:
                    self.peaks[symbol] = current_price
                else:
                    self.peaks[symbol] = max(self.peaks[symbol], current_price)
                
                high_mark = self.peaks[symbol]
                pullback = (high_mark - current_price) / high_mark
                
                if pullback >= self.config["trailing_callback"]:
                    # Secure the bag
                    del self.portfolio[symbol]
                    del self.peaks[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': ['TRAILING_PROFIT', f'ROI_{roi:.4f}']
                    }
            else:
                # Reset peak if we dip below trigger (though we don't sell)
                # This ensures we re-evaluate peak if price recovers from a dip that didn't trigger sell
                if symbol in self.peaks and roi < (self.config["min_roi_trigger"] / 2):
                    del self.peaks[symbol]

            # --- DCA REPAIR LOGIC ---
            # Only buy more if significantly lower and we have room
            if roi < -0.01: # Minimum 1% drop to consider DCA
                dca_lvl = pos['dca_level']
                if dca_lvl < self.config["max_dca_count"]:
                    mean, stdev = self._get_stats(symbol)
                    if mean is not None and stdev > self.config["volatility_min"]:
                        # Dynamic Z-score requirement based on DCA level
                        # Level 0->1 needs Z < -3.0
                        # Level 1->2 needs Z < -4.0, etc.
                        target_z = self.config["entry_z_score"] - (dca_lvl * self.config["dca_z_step"])
                        current_z = (current_price - mean) / stdev
                        
                        if current_z < target_z:
                            # Mutation: Confirmation candle. Don't buy a red candle.
                            # Check if current price is higher than previous tick (local reversal)
                            hist = self.prices[symbol]
                            if len(hist) > 2 and hist[-1] > hist[-2]:
                                
                                buy_amt = self.config["base_amt"] * (self.config["dca_multiplier"] ** (dca_lvl + 1))
                                
                                # Update position tracking
                                new_qty = qty + buy_amt
                                new_cost = ((qty * cost) + (buy_amt * current_price)) / new_qty
                                
                                self.portfolio[symbol] = {
                                    'avg_cost': new_cost,
                                    'qty': new_qty,
                                    'dca_level': dca_lvl + 1
                                }
                                
                                return {
                                    'side': 'BUY',
                                    'symbol': symbol,
                                    'amount': buy_amt,
                                    'reason': ['DCA_REPAIR', f'LVL_{dca_lvl + 1}']
                                }

        # 3. Check for New Entries
        if len(self.portfolio) < self.config["max_positions"]:
            # Find best opportunity
            best_opp = None
            lowest_z = self.config["entry_z_score"] # Start at threshold
            
            for symbol, price in prices.items():
                if symbol in self.portfolio: continue
                
                mean, stdev = self._get_stats(symbol)
                if mean is None or stdev < self.config["volatility_min"]: continue
                
                z_score = (price - mean) / stdev
                
                if z_score < lowest_z:
                    # Filter: Momentum check. If RSI-like behavior is too weak, wait.
                    # Simple heuristic: Price must be < Mean * 0.99 (1% deviation minimum absolute)
                    # to avoid trading noise on low vol assets
                    if price < mean * 0.995:
                         lowest_z = z_score
                         best_opp = symbol
            
            if best_opp:
                amt = self.config["base_amt"]
                self.portfolio[best_opp] = {
                    'avg_cost': prices[best_opp],
                    'qty': amt,
                    'dca_level': 0
                }
                return {
                    'side': 'BUY',
                    'symbol': best_opp,
                    'amount': amt,
                    'reason': ['ENTRY_ALPHA', f'Z_{lowest_z:.2f}']
                }
        
        return {}