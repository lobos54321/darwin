import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        # STRATEGY: DEEP VALUE MEAN REVERSION (NO STOP LOSS)
        # PENALTY FIX: 
        # 1. "STOP_LOSS": Removed trailing stop/callback logic which can trigger sells on pullbacks.
        #    Replaced with STRICT Take-Profit Limit logic (Sell only into strength).
        # 2. "DIP_BUY": Enforced stricter entry conditions (Z-Score < -3.2 AND RSI < 30).
        # 3. DCA: Uses Martingale repair to lower average cost during drawdowns.
        
        self.window_size = 50
        # Storage: symbol -> deque of prices
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio: symbol -> {'avg_cost': float, 'qty': float, 'dca_level': int}
        self.portfolio = {}
        
        self.config = {
            "max_positions": 5,
            "base_amt": 10.0,
            
            # Entry Filters (Strict Deep Value)
            "entry_z_score": -3.2,      # Requires 3.2 std deviation drop
            "entry_rsi_max": 30,        # Must be oversold
            "min_volatility": 1e-6,     # Avoid flat assets
            
            # Exit Logic (Profit Taking Only - No Stops)
            "take_profit_roi": 0.025,   # Sell entire position at 2.5% gain
            
            # DCA Defense (Lower Average Cost)
            "max_dca": 3,
            "dca_triggers": [-0.03, -0.06, -0.10], # Add size at -3%, -6%, -10% PnL
            "dca_mult": 1.5             # Size multiplier
        }

    def _get_indicators(self, symbol):
        data = self.prices[symbol]
        if len(data) < 20:
            return None, None
        
        try:
            # Z-Score Calculation
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
            if stdev < self.config["min_volatility"]:
                return None, None
            
            current_price = data[-1]
            z_score = (current_price - mean) / stdev
            
            # RSI Calculation (14-period approx)
            if len(data) < 15:
                # Not enough data for RSI, return neutral
                return z_score, 50.0
            
            deltas = [data[i] - data[i-1] for i in range(len(data)-14, len(data))]
            gains = [d for d in deltas if d > 0]
            losses = [-d for d in deltas if d < 0]
            
            avg_gain = sum(gains) / 14.0
            avg_loss = sum(losses) / 14.0
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
            return z_score, rsi
            
        except Exception:
            return None, None

    def on_price_update(self, prices):
        # 1. Update Market Data
        for symbol, price in prices.items():
            self.prices[symbol].append(price)

        # 2. Manage Existing Positions (Exits & DCA)
        # We sort positions by ROI descending to secure profits first
        active_positions = []
        for symbol, pos in self.portfolio.items():
            current_price = prices[symbol]
            cost = pos['avg_cost']
            roi = (current_price - cost) / cost
            active_positions.append((symbol, roi))
        
        active_positions.sort(key=lambda x: x[1], reverse=True)

        for symbol, roi in active_positions:
            pos = self.portfolio[symbol]
            qty = pos['qty']
            current_price = prices[symbol]

            # --- EXIT LOGIC ---
            # Strictly Positive ROI exit. No Trailing Stop.
            if roi >= self.config["take_profit_roi"]:
                del self.portfolio[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f'ROI_{roi:.4f}']
                }

            # --- DCA LOGIC ---
            # If price drops, buy more to lower avg_cost
            dca_level = pos['dca_level']
            if dca_level < self.config["max_dca"]:
                trigger_roi = self.config["dca_triggers"][dca_level]
                
                if roi < trigger_roi:
                    # Sanity Check: Ensure trend isn't completely broken
                    z, rsi = self._get_indicators(symbol)
                    
                    # Only DCA if asset is still considered "oversold" or neutral
                    # Avoid adding to a position if Z-score has spiked up without price recovery
                    if z is not None and z < -1.0: 
                        buy_amt = self.config["base_amt"] * (self.config["dca_mult"] ** (dca_level + 1))
                        
                        # Update position with weighted average cost
                        new_qty = qty + buy_amt
                        total_cost = (qty * pos['avg_cost']) + (buy_amt * current_price)
                        new_avg_cost = total_cost / new_qty
                        
                        self.portfolio[symbol] = {
                            'avg_cost': new_avg_cost,
                            'qty': new_qty,
                            'dca_level': dca_level + 1
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': buy_amt,
                            'reason': ['DCA_REPAIR', f'LVL_{dca_level+1}']
                        }

        # 3. Check for New Entries
        if len(self.portfolio) < self.config["max_positions"]:
            best_candidate = None
            lowest_z = self.config["entry_z_score"] # Start threshold
            
            for symbol, price in prices.items():
                if symbol in self.portfolio:
                    continue
                
                z, rsi = self._get_indicators(symbol)
                if z is None:
                    continue
                
                # Strict Intersection: Deep Z-Score AND Low RSI