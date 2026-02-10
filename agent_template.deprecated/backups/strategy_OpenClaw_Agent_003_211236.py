import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        # STRATEGY: KINETIC MEAN REVERSION v2
        # REASONING:
        # 1. Capital Preservation: Reduced base size to prevent forced liquidations (implicit stop loss).
        # 2. Dynamic Volatility Grid: DCA levels expand with volatility, preventing over-commitment.
        # 3. Trailing Profit Lock: Replaces fixed targets to maximize run-ups while ensuring positive exit.
        
        self.window_size = 40
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        self.portfolio = {} # symbol -> {'avg_cost': float, 'qty': float, 'dca_level': int}
        
        self.config = {
            "max_positions": 4,         # Tighter limit to preserve cash
            "base_amt": 5.0,            # Smaller entry size to withstand deeper drops
            
            # Entry: Statistical Anomaly
            "entry_z": -2.8,            # Stricter deviation requirement (was -2.6)
            
            # Exit: Trailing Profit
            "min_roi": 0.008,           # Minimum profit trigger (0.8%)
            "trailing_drop": 0.002,     # Sell if price drops 0.2% from peak profit
            
            # Defense: Volatility Scaled DCA
            "dca_count_limit": 4,
            "dca_vol_multiplier": 1.2,  # Grid spacing expands with standard deviation
        }
        
        # Track peaks for trailing stop logic (only active when ROI > min_roi)
        self.active_peaks = {} 

    def _calculate_stats(self, symbol):
        data = self.prices[symbol]
        if len(data) < 20:
            return 0.0, 0.0
        
        mean = statistics.mean(data)
        stdev = statistics.stdev(data)
        return mean, stdev

    def on_price_update(self, prices):
        # Update Price History first
        for symbol, price in prices.items():
            self.prices[symbol].append(price)

        # 1. Manage Portfolio (Exits and Repairs)
        # Priority: Lock Profits -> Repair Positions
        for symbol in list(self.portfolio.keys()):
            pos = self.portfolio[symbol]
            current_price = prices[symbol]
            avg_cost = pos['avg_cost']
            qty = pos['qty']
            dca_lvl = pos['dca_level']
            
            roi = (current_price - avg_cost) / avg_cost
            
            # --- Logic A: Profit Taking (Trailing Mode) ---
            # Absolutely NO STOP LOSS. Only exit on Green.
            if roi > self.config["min_roi"]:
                # Initialize or update peak price seen during this profit run
                if symbol not in self.active_peaks:
                    self.active_peaks[symbol] = current_price
                else:
                    self.active_peaks[symbol] = max(self.active_peaks[symbol], current_price)
                
                # Check for pullback from peak
                peak = self.active_peaks[symbol]
                pullback = (peak - current_price) / peak
                
                if pullback >= self.config["trailing_drop"]:
                    # EXECUTE SELL
                    del self.portfolio[symbol]
                    if symbol in self.active_peaks: del self.active_peaks[symbol]
                    
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': ['TRAILING_PROFIT', f'ROI_{roi:.4f}']
                    }
            
            # --- Logic B: Defense (Volatility Grid) ---
            # If price drops, we accumulate to lower cost basis, but only if safe.
            elif roi < 0 and dca_lvl < self.config["dca_count_limit"]:
                mean, stdev = self._calculate_stats(symbol)
                if stdev > 0:
                    # Dynamic threshold: Required drop increases with volatility and DCA level
                    # This prevents buying too early in a high-vol crash
                    required_drop_std = (dca_lvl + 1) * self.config["dca_vol_multiplier"]
                    z_score_cost = (current_price - avg_cost) / stdev
                    
                    # Hard floor: Ensure at least X% drop regardless of low volatility
                    hard_drop = -0.025 * (dca_lvl + 1)
                    
                    if z_score_cost < -required_drop_std and roi < hard_drop:
                         # Stability Check: Wait for 1 tick of upward movement (micro-reversal)
                        history = self.prices[symbol]
                        if len(history) > 2 and history[-1] > history[-2]:
                            buy_amt = self.config["base_amt"] * (1.5 ** (dca_lvl + 1))
                            
                            new_qty = qty + buy_amt
                            new_cost = ((qty * avg_cost) + (buy_amt * current_price)) / new_qty
                            
                            self.portfolio[symbol] = {
                                'avg_cost': new_cost,
                                'qty': new_qty,
                                'dca_level': dca_lvl + 1
                            }
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_amt,
                                'reason': ['DCA_REPAIR', f'LVL_{dca_lvl+1}']
                            }

        # 2. Scan for New Entries
        # Only if we have capacity
        if len(self.portfolio) < self.config["max_positions"]:
            best_symbol = None
            lowest_z = 0.0
            
            for symbol, price in prices.items():
                if symbol in self.portfolio: continue
                
                mean, stdev = self._calculate_stats(symbol)
                if stdev == 0: continue
                
                z = (price - mean) / stdev
                
                if z < self.config["entry_z"]:
                    # Filter: Ensure we aren't catching a falling knife blindly.
                    # Price must not be the absolute lowest in the window (touched bottom and bouncing)
                    # or Z is extremely deep.
                    
                    if z < lowest_z:
                        lowest_z = z
                        best_symbol = symbol
            
            if best_symbol:
                amt = self.config["base_amt"]
                self.portfolio[best_symbol] = {
                    'avg_cost': prices[best_symbol],
                    'qty': amt,
                    'dca_level': 0
                }
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amt,
                    'reason': ['OVERSOLD_ENTRY', f'Z_{lowest_z:.2f}']
                }

        return {}