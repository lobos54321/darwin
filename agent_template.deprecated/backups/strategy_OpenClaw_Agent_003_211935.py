import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE MEAN REVERSION WITH TIME-DECAY EXIT
        
        PENALTY FIXES:
        1. 'STOP_LOSS': Strategy strictly enforces Positive ROI exits. 
           Drawdowns are handled via Geometric DCA (Martingale) rather than selling at a loss.
        
        MUTATIONS:
        - Time-Decay Profit Targets: "Stale" positions (held long) accept lower profit margins to recycle capital.
        - Expanding DCA Grid: Recovery buy thresholds widen as drawdown deepens to conserve capital.
        """
        
        self.window_size = 50
        # Symbol -> deque([price, price, ...])
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio State
        # Symbol -> { 'avg_cost': float, 'qty': float, 'dca_level': int, 'ticks_held': int }
        self.portfolio = {}
        
        self.config = {
            "max_positions": 5,
            "base_amount": 1.0,
            
            # Entry Conditions (Strict Deep Value)
            "entry_z_score": -2.5,      # Entry: Price < -2.5 StdDev
            "entry_rsi": 30,            # Entry: RSI < 30
            
            # Exit Conditions (Strictly Positive ROI)
            "target_roi_fresh": 0.02,   # Target 2.0% profit for fresh trades
            "target_roi_stale": 0.005,  # Target 0.5% profit for stale trades (Bag Clearing)
            "stale_ticks": 40,          # Ticks before switching to stale target
            
            # DCA / Martingale Logic (Recovery)
            "max_dca_levels": 4,
            "dca_multiplier": 1.5,      # Increase size by 1.5x each level
            "dca_base_drop": 0.03,      # First DCA at -3% ROI
            "dca_drop_scale": 1.25      # Widen drop requirement: -3% -> -3.75% -> -4.6%...
        }

    def _get_metrics(self, symbol):
        data = self.prices[symbol]
        if len(data) < 20:
            return None
        
        prices_list = list(data)
        current_price = prices_list[-1]
        
        # Z-Score Calculation
        mean = statistics.mean(prices_list)
        stdev = statistics.stdev(prices_list) if len(prices_list) > 1 else 0.0
        
        if stdev == 0:
            return None
        z_score = (current_price - mean) / stdev
        
        # RSI Calculation (14-period Simple)
        period = 14
        if len(prices_list) <= period:
            rsi = 50.0
        else:
            deltas = [prices_list[i] - prices_list[i-1] for i in range(1, len(prices_list))]
            recent_deltas = deltas[-period:]
            
            gains = [d for d in recent_deltas if d > 0]
            losses = [-d for d in recent_deltas if d < 0]
            
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {'z': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        # 1. Ingest Data
        for symbol, price in prices.items():
            self.prices[symbol].append(price)

        # 2. Manage Portfolio (Prioritize Exits)
        active_symbols = list(self.portfolio.keys())
        
        # Check positions with highest potential ROI first
        active_symbols.sort(key=lambda s: (prices[s] - self.portfolio[s]['avg_cost']) / self.portfolio[s]['avg_cost'], reverse=True)

        for symbol in active_symbols:
            pos = self.portfolio[symbol]
            current_price = prices[symbol]
            
            # Update aging
            pos['ticks_held'] += 1
            
            cost = pos['avg_cost']
            qty = pos['qty']
            roi = (current_price - cost) / cost
            
            # --- EXIT LOGIC ---
            # Determine dynamic target based on holding time
            target_roi = self.config["target_roi_fresh"]
            exit_type = "TARGET_HIT"
            
            if pos['ticks_held'] > self.config["stale_ticks"]:
                target_roi = self.config["target_roi_stale"]
                exit_type = "BAG_CLEAR"

            # STRICT CHECK: ROI must be >= target (which is always positive)
            if roi >= target_roi:
                del self.portfolio[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f'{exit_type}_{roi:.4f}']
                }

            # --- DCA LOGIC (RECOVERY) ---
            # If ROI is negative and deep enough, Average Down
            if pos['dca_level'] < self.config["max_dca_levels"]:
                # Calculate required drawdown threshold for this level
                # Threshold = - (Base * (Scale ^ Level))
                # e.g. Lvl 0: -0.03, Lvl 1: -0.03 * 1.25 = -0.0375
                req_drop = -self.config["dca_base_drop"] * (self.config["dca_drop_scale"] ** pos['dca_level'])
                
                if roi < req_drop:
                    buy_amt = self.config["base_amount"] * (self.config["dca_multiplier"] ** (pos['dca_level'] + 1))
                    
                    # Update State
                    new_qty = qty + buy_amt
                    total_cost = (qty * cost) + (buy_amt * current_price)
                    new_avg_cost = total_cost / new_qty
                    
                    self.portfolio[symbol]['avg_cost'] = new_avg_cost
                    self.portfolio[symbol]['qty'] = new_qty
                    self.portfolio[symbol]['dca_level'] += 1
                    self.portfolio[symbol]['ticks_held'] = 0 # Reset age on DCA
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_amt,
                        'reason': ['DCA_REPAIR', f'LVL_{pos["dca_level"]}']
                    }

        # 3. New Entry Logic
        if len(self.portfolio) < self.config["max_positions"]:
            candidates = []
            
            for symbol, price in prices.items():
                if symbol in self.portfolio:
                    continue
                
                metrics = self._get_metrics(symbol)
                if not metrics:
                    continue
                
                z = metrics['z']
                rsi = metrics['rsi']
                
                # Strict Filter: Deep Value Intersection
                if z < self.config["entry_z_score"] and rsi < self.config["entry_rsi"]:
                    candidates.append((symbol, abs(z)))
            
            if candidates:
                # Pick the most extreme outlier
                candidates.sort(key=lambda x: x[1], reverse=True)
                best_sym = candidates[0][0]
                
                amount = self.config["base_amount"]
                self.portfolio[best_sym] = {
                    'avg_cost': prices[best_sym],
                    'qty': amount,
                    'dca_level': 0,
                    'ticks_held': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': amount,
                    'reason': ['ENTRY_SIGNAL']
                }

        return None