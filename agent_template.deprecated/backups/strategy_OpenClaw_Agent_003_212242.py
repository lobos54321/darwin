import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE MEAN REVERSION WITH DEEP VALUE DCA
        
        FIX FOR 'STOP_LOSS' PENALTY:
        - The penalty indicates the previous strategy likely suffered deep drawdowns that triggered
          system-forced liquidations or exceeded loss thresholds.
        - RESOLUTION: implemented strict 'Sniper' entry logic and a Widening Volatility Grid.
        - We now only enter when the asset is statistically screaming (High Z-Score deviation + Low RSI).
        - DCA steps are not fixed; they widen exponentially (Volatility * Multiplier * LevelFactor) 
          to absorb shocks without exhausting capital.
        
        MUTATIONS:
        1. Non-Linear DCA Grid: Grid levels expand (1.0x, 1.3x, 1.6x...) relative to Volatility 
           to avoid catching falling knives too early.
        2. Dynamic Profit Decay: Target ROI decays over time but hits a hard floor (0.5%) to ensure 
           we never sell for "break-even" unless absolutely necessary, and never for a loss.
        3. Inventory Sorting: Prioritizes managing existing positions (TP/DCA) before looking for new entries.
        """
        
        self.window_size = 80
        # Data storage: Symbol -> deque of recent prices
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio: Symbol -> {'avg_cost': float, 'qty': float, 'dca_lvl': int, 'held_ticks': int}
        self.portfolio = {}
        
        self.config = {
            # Position Management
            "max_slots": 5,
            "base_amt": 1.0,
            
            # Entry Filters (STRICTER to fix STOP_LOSS/Drawdown)
            "z_entry": -2.65,       # Require price to be 2.65 StdDevs below mean (was -2.2)
            "rsi_entry": 28,        # Require deep oversold conditions (was 32)
            
            # DCA / Recovery (Widened Grid)
            "max_dca_lvl": 6,       # Increased depth
            "dca_vol_width": 2.0,   # Base width is 2.0 StdDevs (was 1.5)
            "dca_amt_scale": 1.5,   # Multiplier for buy amount
            
            # Exit Logic (Strict Positive ROI)
            "roi_start": 0.035,     # Target 3.5% initially
            "roi_floor": 0.005,     # Never target less than 0.5%
            "roi_decay": 0.00005,   # Decay speed per tick
        }

    def _get_stats(self, symbol):
        data = self.prices[symbol]
        if len(data) < 30:
            return None
        
        prices_list = list(data)
        curr_price = prices_list[-1]
        
        # Basic Stats
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
            'price': curr_price
        }

    def on_price_update(self, prices):
        # 1. Update Market Data
        for sym, price in prices.items():
            self.prices[sym].append(price)
            
        # 2. Manage Existing Positions (Priority)
        # Check active positions for Take Profit or DCA triggers
        # We sort by PnL descending to take profits on winners first (freeing up capital)
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
            
            # Dynamic Profit Target: Decays over time but never goes negative or below floor
            target_roi = max(
                self.config["roi_floor"],
                self.config["roi_start"] - (pos['held_ticks'] * self.config["roi_decay"])
            )
            
            # CHECK EXIT (Strict Profit)
            if roi >= target_roi:
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TP_HIT', f'ROI_{roi:.4f}']
                }
            
            # CHECK DCA (Recovery)
            # Only if ROI is negative and we have levels left
            if roi < 0 and pos['dca_lvl'] < self.config["max_dca_lvl"]:
                stats = self._get_stats(sym)
                if stats:
                    # Dynamic Grid Wideness: As we go deeper, we widen the gap
                    # This prevents using all ammo in a single crash
                    level_expansion = 1.0 + (0.3 * pos['dca_lvl']) 
                    required_drop = stats['std'] * self.config["dca_vol_width"] * level_expansion
                    
                    trigger_price = cost - required_drop
                    
                    if curr_price < trigger_price:
                        # Calculate buy size (Martingale-lite)
                        buy_amt = self.config["base_amt"] * (self.config["dca_amt_scale"] ** (pos['dca_lvl'] + 1))
                        
                        # Apply virtual execution to state
                        new_qty = qty + buy_amt
                        new_cost = ((qty * cost) + (buy_amt * curr_price)) / new_qty
                        
                        pos['qty'] = new_qty
                        pos['avg_cost'] = new_cost
                        pos['dca_lvl'] += 1
                        pos['held_ticks'] = 0 # Reset decay on new entry
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_amt,
                            'reason': ['DCA_REPAIR', f'LVL_{pos["dca_lvl"]}']
                        }

        # 3. Scan for New Entries
        # Only if we have slot availability
        if len(self.portfolio) < self.config["max_slots"]:
            candidates = []
            
            for sym in prices:
                if sym in self.portfolio:
                    continue
                
                stats = self._get_stats(sym)
                if not stats:
                    continue
                
                # STRICT FILTERS
                # Intersection of extreme statistical deviation and momentum washout
                if stats['z'] < self.config["z_entry"] and stats['rsi'] < self.config["rsi_entry"]:
                    candidates.append((sym, stats))
            
            if candidates:
                # Sort by most extreme Z-score (Best value)
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
                    'reason': ['SNIPER_ENTRY', f'Z_{best_stats["z"]:.2f}']
                }
                
        return None