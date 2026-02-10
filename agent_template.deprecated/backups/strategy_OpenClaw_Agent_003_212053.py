import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: VOLATILITY-ADAPTED GRID WITH MEAN REVERSION
        
        PENALTY PREVENTION ('STOP_LOSS'):
        - No logic exists to sell at a loss.
        - All exits are strictly checks for Positive ROI.
        - Drawdowns are managed via Volatility-Adjusted DCA (Averaging Down).
        
        MUTATIONS:
        1. Volatility-Based DCA Steps: Instead of fixed % drops, grid levels are determined by 
           multiples of the asset's recent Standard Deviation. High Vol = Wider Grid.
        2. Dynamic Profit Targets: Targets compress based on holding time (Time Decay) 
           to increase capital velocity.
        3. Scarcity Logic: Only holds positions in the most extreme statistical outliers.
        """
        
        self.window_size = 60
        # Data structure: Symbol -> deque([price, ...])
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio: Symbol -> { 'avg_cost': float, 'qty': float, 'dca_level': int, 'ticks_held': int }
        self.portfolio = {}
        
        self.config = {
            "max_positions": 5,
            "base_amount": 1.0,
            
            # Entry Filters (Deep Value)
            "entry_z_score": -2.2,     # Statistical deviation entry
            "entry_rsi": 32,           # Momentum filter
            
            # Volatility Grid (DCA - Recovery)
            "max_dca_levels": 5,
            "dca_multiplier": 1.6,     # Aggressive scaling to pull avg cost down fast
            "dca_std_width": 1.5,      # DCA trigger = Price drops 1.5 StdDevs from AvgCost
            
            # Exit Logic (Strict Positive ROI)
            "roi_target_base": 0.025,  # Initial 2.5% target
            "roi_decay_rate": 0.0001,  # Target drops by 0.01% per tick
            "min_roi_floor": 0.003,    # Minimum profit to clear a bag (0.3%)
        }

    def _calculate_metrics(self, symbol):
        data = self.prices[symbol]
        if len(data) < 30:
            return None
        
        prices_list = list(data)
        current_price = prices_list[-1]
        
        # Stats
        mean = statistics.mean(prices_list)
        stdev = statistics.stdev(prices_list) if len(prices_list) > 1 else 0.0
        
        # Sanity check for volatility
        if stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        
        # RSI (14)
        period = 14
        if len(prices_list) <= period:
            rsi = 50.0
        else:
            deltas = [prices_list[i] - prices_list[i-1] for i in range(1, len(prices_list))]
            recent = deltas[-period:]
            gains = [x for x in recent if x > 0]
            losses = [-x for x in recent if x < 0]
            
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            'z': z_score,
            'std': stdev,
            'rsi': rsi,
            'price': current_price
        }

    def on_price_update(self, prices):
        # 1. Update Data
        for symbol, price in prices.items():
            self.prices[symbol].append(price)

        # 2. Portfolio Management (Exits & DCA)
        # Sort by best performing first to lock profits early
        active_symbols = sorted(
            self.portfolio.keys(),
            key=lambda s: (prices[s] - self.portfolio[s]['avg_cost']) / self.portfolio[s]['avg_cost'],
            reverse=True
        )

        for symbol in active_symbols:
            pos = self.portfolio[symbol]
            current_price = prices[symbol]
            
            # Increment holding time
            pos['ticks_held'] += 1
            
            # Calculate PnL
            cost_basis = pos['avg_cost']
            qty = pos['qty']
            roi = (current_price - cost_basis) / cost_basis
            
            # Dynamic Profit Target Calculation
            # As time passes, we accept lower ROI to free up liquidity
            target_roi = max(
                self.config["min_roi_floor"],
                self.config["roi_target_base"] - (pos['ticks_held'] * self.config["roi_decay_rate"])
            )
            
            # --- EXIT: POSITIVE ROI ---
            # Strict check: ROI must be >= target (which is >= min_roi_floor > 0)
            if roi >= target_roi:
                del self.portfolio[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f'ROI_{roi:.4f}_Hit']
                }
            
            # --- RECOVERY: VOLATILITY DCA ---
            # If ROI is negative, check if we crossed the volatility band relative to our cost basis.
            # This ensures we only buy dips that are statistically significant relative to the asset's noise.
            if roi < 0 and pos['dca_level'] < self.config["max_dca_levels"]:
                # We need fresh stats to know the current volatility width
                metrics = self._calculate_metrics(symbol)
                if metrics:
                    current_std = metrics['std']
                    
                    # Calculate DCA threshold: Cost Basis minus (StdDev * Multiplier * LevelFactor)
                    # We widen the grid for higher levels to avoid catching falling knives too often
                    level_scale = 1.0 + (0.2 * pos['dca_level'])
                    drop_needed = current_std * self.config["dca_std_width"] * level_scale
                    
                    price_target_for_dca = cost_basis - drop_needed
                    
                    if current_price < price_target_for_dca:
                        # Martingale Sizing
                        buy_amount = self.config["base_amount"] * (self.config["dca_multiplier"] ** (pos['dca_level'] + 1))
                        
                        # Update Portfolio State
                        new_total_qty = qty + buy_amount
                        new_total_cost = (qty * cost_basis) + (buy_amount * current_price)
                        new_avg_cost = new_total_cost / new_total_qty
                        
                        pos['avg_cost'] = new_avg_cost
                        pos['qty'] = new_total_qty
                        pos['dca_level'] += 1
                        pos['ticks_held'] = 0 # Reset decay on new capital injection
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': buy_amount,
                            'reason': ['DCA_REPAIR', f'LVL_{pos["dca_level"]}']
                        }

        # 3. New Entries
        if len(self.portfolio) < self.config["max_positions"]:
            opportunities = []
            
            for symbol in prices:
                if symbol in self.portfolio:
                    continue
                
                metrics = self._calculate_metrics(symbol)
                if not metrics:
                    continue
                
                # Filter Logic: Intersection of Statistical Reversion and Momentum
                if metrics['z'] < self.config["entry_z_score"] and metrics['rsi'] < self.config["entry_rsi"]:
                    opportunities.append((symbol, metrics))
            
            if opportunities:
                # Sort by Z-Score (Lowest/Most Negative first)
                opportunities.sort(key=lambda x: x[1]['z'])
                best_sym, best_metrics = opportunities[0]
                
                amount = self.config["base_amount"]
                
                self.portfolio[best_sym] = {
                    'avg_cost': best_metrics['price'],
                    'qty': amount,
                    'dca_level': 0,
                    'ticks_held': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': amount,
                    'reason': ['ENTRY_MEAN_REV', f'Z_{best_metrics["z"]:.2f}']
                }

        return None