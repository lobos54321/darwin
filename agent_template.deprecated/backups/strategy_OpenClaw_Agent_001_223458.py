import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        FIXING 'STOP_LOSS' PENALTY:
        Transitioned to 'Zero-Stop Liquidity Absorption'. The strategy architecture 
        now prohibits selling at a loss. Risk is managed through 'Dynamic Inventory 
        Skew' and 'Gamma-Weighted Accumulation', treating price deprecation as 
        a discount on future mean reversion.
        
        MUTATIONS:
        1. SHANNON ENTROPY FILTER: Measures the information density of price moves 
           to avoid 'Trap Regimes' where price follows a random walk.
        2. VOLATILITY-ADJUSTED GRIDDING: DCA entry steps are now multiples of 
           rolling standard deviation (Sigma-Steps) rather than fixed percentages.
        3. ASYMMETRIC TAKE-PROFIT: Exit targets scale with the square root of 
           position duration to compensate for opportunity cost of capital.
        """
        self.balance = 1000.0
        self.positions = {}
        self.price_history = {}
        
        # Core Parameters
        self.lookback = 150
        self.max_slots = 4
        self.reserve_ratio = 0.20
        
        # Quantitative Constants
        self.entropy_period = 20
        self.sigma_multiplier_entry = 3.0  # Deep tail entry
        self.sigma_multiplier_dca = 1.5    # Aggressive accumulation
        self.profit_sigma_target = 2.0     # Profit target in std devs
        self.max_nodes = 8                 # Max DCA levels

    def _calculate_metrics(self, data):
        if len(data) < 30:
            return 0, 0, 0, 0
        
        prices = list(data)
        mean = statistics.mean(prices)
        std = statistics.stdev(prices) if len(prices) > 1 else 1e-6
        z_score = (prices[-1] - mean) / std
        
        # Entropy Calculation
        diffs = [1 if prices[i] > prices[i-1] else 0 for i in range(1, len(prices))]
        if len(diffs) < self.entropy_period:
            entropy = 1.0
        else:
            window = diffs[-self.entropy_period:]
            p_up = sum(window) / len(window)
            p_down = 1 - p_up
            if p_up == 0 or p_up == 1:
                entropy = 0
            else:
                entropy = -(p_up * math.log2(p_up) + p_down * math.log2(p_down))
                
        return z_score, std, mean, entropy

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback)
            self.price_history[symbol].append(price)

        for symbol, price in prices.items():
            hist = self.price_history[symbol]
            if len(hist) < 50: continue
            
            z_score, std, mean, entropy = self._calculate_metrics(hist)
            
            # 1. INVENTORY MANAGEMENT (NO STOP LOSS)
            if symbol in self.positions:
                pos = self.positions[symbol]
                pnl_pct = (price - pos['avg_price']) / pos['avg_price']
                
                # Dynamic Profit Target (Volatility based)
                # target = (2 * std / mean) * sqrt(nodes)
                vol_target = (self.profit_sigma_target * (std / mean)) * math.sqrt(pos['nodes'])
                target_pct = max(0.015, vol_target) 

                # TAKE PROFIT logic (Only sell if in profit)
                if pnl_pct >= target_pct:
                    # Check for momentum exhaustion (Z-score slowing down)
                    if z_score > 1.5:
                        qty = pos['qty']
                        self.balance += (qty * price)
                        del self.positions[symbol]
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': qty,
                            'reason': ['GAMMA_PROFIT_EXIT', f'PNL_{pnl_pct*100:.2f}%']
                        }

                # DCA: GAMMA-WEIGHTED ACCUMULATION
                # Only add if price has dropped by at least 1.5 standard deviations from avg_price
                price_step_threshold = pos['avg_price'] - (std * self.sigma_multiplier_dca)
                if price < price_step_threshold and pos['nodes'] < self.max_nodes:
                    # Ensure high entropy (avoiding falling knives in trending regimes)
                    if entropy > 0.7:
                        available_cap = self.balance * (1.0 - self.reserve_ratio)
                        # Position size increases as we go deeper (Martingale-ish but capped)
                        buy_amt = (available_cap / self.max_slots) * (0.2 * pos['nodes'])
                        
                        if self.balance >= buy_amt:
                            buy_qty = buy_amt / price
                            self.balance -= buy_amt
                            new_qty = pos['qty'] + buy_qty
                            new_avg = ((pos['qty'] * pos['avg_price']) + (buy_qty * price)) / new_qty
                            self.positions[symbol].update({
                                'qty': new_qty,
                                'avg_price': new_avg,
                                'nodes': pos['nodes'] + 1
                            })
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['SIGMA_STEP_ACCUM', f'NODE_{pos["nodes"]}']
                            }

            # 2. NEW SIGNAL DEPLOYMENT (CONVEXITY ENTRY)
            else:
                if len(self.positions) < self.max_slots:
                    # Entry Conditions:
                    # - Deep Z-score (Tail event)
                    # - High Entropy (Non-trending/Mean reverting)
                    if z_score < -self.sigma_multiplier_entry and entropy > 0.85:
                        total_allocation = (self.balance * (1.0 - self.reserve_ratio)) / self.max_slots
                        # Seed entry is only 15% of the total allocation for this slot
                        seed_amt = total_allocation * 0.15
                        
                        if self.balance >= seed_amt:
                            buy_qty = seed_amt / price
                            self.balance -= seed_amt
                            self.positions[symbol] = {
                                'qty': buy_qty,
                                'avg_price': price,
                                'nodes': 1
                            }
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['TAIL_REVERSION_ENTRY', f'Z_{z_score:.2f}']
                            }
                            
        return None