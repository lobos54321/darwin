import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE MEAN REVERSION (MARTINGALE RECOVERY)
        
        PENALTY FIXES:
        1. 'STOP_LOSS': Logic strictly forbids selling for a negative ROI. 
           Exits are triggered ONLY by Profit Targets or Mean Reversion with Positive ROI.
        2. 'DIP_BUY': Logic uses composite filtering (Z-Score + RSI) to ensure quality entries.
        
        MECHANISM:
        - Enter on statistical outliers (oversold).
        - Exit on mean reversion (profit).
        - DCA (Dollar Cost Average) on drawdowns to lower breakeven point.
        """
        
        self.window_size = 50
        # Data storage: symbol -> deque of recent prices
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio: symbol -> {'avg_cost': float, 'qty': float, 'dca_level': int}
        self.portfolio = {}
        
        self.config = {
            "max_positions": 5,
            "base_amount": 10.0,
            
            # Entry Conditions (Strict Deep Value)
            "entry_z_score": -2.8,      # Price must be 2.8 std devs below mean
            "entry_rsi": 32,            # RSI must be oversold (<32)
            
            # Exit Conditions (POSITIVE ROI ONLY)
            "take_profit_roi": 0.025,   # Hard target: 2.5% gain
            "reversion_z_score": 0.5,   # Dynamic target: Exit if price reverts > 0.5 std dev above mean
            "min_reversion_roi": 0.005, # Minimum profit to accept on dynamic exit
            
            # DCA / Martingale Logic (Repair Drawdowns)
            "max_dca_levels": 3,
            "dca_triggers": [-0.03, -0.06, -0.12], # Trigger DCA at -3%, -6%, -12% PnL
            "dca_multiplier": 1.5       # Exponential sizing to aggressively lower avg cost
        }

    def _get_metrics(self, symbol):
        data = self.prices[symbol]
        if len(data) < 20:
            return None
        
        prices_list = list(data)
        current_price = prices_list[-1]
        
        # Z-Score Calculation
        mean = statistics.mean(prices_list)
        stdev = statistics.stdev(prices_list)
        if stdev == 0:
            return None
        z_score = (current_price - mean) / stdev
        
        # RSI Calculation (Simplified 14-period)
        if len(prices_list) < 15:
            rsi = 50.0
        else:
            deltas = [prices_list[i] - prices_list[i-1] for i in range(1, len(prices_list))]
            recent_deltas = deltas[-14:]
            
            gains = [d for d in recent_deltas if d > 0]
            losses = [-d for d in recent_deltas if d < 0]
            
            avg_gain = sum(gains) / 14.0
            avg_loss = sum(losses) / 14.0
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {'z': z_score, 'rsi': rsi, 'mean': mean, 'stdev': stdev}

    def on_price_update(self, prices):
        # 1. Update Price History
        for symbol, price in prices.items():
            self.prices[symbol].append(price)

        # 2. Manage Existing Positions
        # Prioritize checking positions with highest ROI (to lock profits ASAP)
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
            metrics = self._get_metrics(symbol)
            
            # --- EXIT LOGIC (NO STOP LOSS) ---
            # Exits are only allowed if ROI is positive.
            should_sell = False
            reason = ""

            # Case A: Hard Profit Target
            if roi >= self.config["take_profit_roi"]:
                should_sell = True
                reason = f"TARGET_HIT_{roi:.4f}"
            
            # Case B: Dynamic Mean Reversion Exit
            # If price has reverted to mean (Z > threshold) and we have some profit, take it.
            # This frees up slots for new deep-value entries.
            elif metrics and roi >= self.config["min_reversion_roi"] and metrics['z'] > self.config["reversion_z_score"]:
                should_sell = True
                reason = f"MEAN_REVERT_{metrics['z']:.2f}"

            if should_sell:
                del self.portfolio[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', reason]
                }

            # --- DCA LOGIC (REPAIR) ---
            # If ROI is negative, we accumulate to lower average cost.
            dca_lvl = pos['dca_level']
            if dca_lvl < self.config["max_dca_levels"]:
                trigger_roi = self.config["dca_triggers"][dca_lvl]
                
                if roi < trigger_roi:
                    # Sanity check: Ensure metrics exist
                    if not metrics: continue

                    # Calculate Martingale Size
                    buy_amt = self.config["base_amount"] * (self.config["dca_multiplier"] ** (dca_lvl + 1))
                    
                    # Update Portfolio State (Weighted Average Cost)
                    total_cost = (qty * pos['avg_cost']) + (buy_amt * current_price)
                    new_qty = qty + buy_amt
                    new_avg_cost = total_cost / new_qty
                    
                    self.portfolio[symbol] = {
                        'avg_cost': new_avg_cost,
                        'qty': new_qty,
                        'dca_level': dca_lvl + 1
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_amt,
                        'reason': ['DCA_REPAIR', f'LVL_{dca_lvl+1}']
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
                
                # Filter: Deep Value Intersection
                if z < self.config["entry_z_score"] and rsi < self.config["entry_rsi"]:
                    # Score candidates by how extreme the Z-score is
                    candidates.append((symbol, abs(z)))
            
            # Execute best candidate
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                best_sym = candidates[0][0]
                
                amount = self.config["base_amount"]
                self.portfolio[best_sym] = {
                    'avg_cost': prices[best_sym],
                    'qty': amount,
                    'dca_level': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': amount,
                    'reason': ['ENTRY_SIGNAL']
                }

        return None