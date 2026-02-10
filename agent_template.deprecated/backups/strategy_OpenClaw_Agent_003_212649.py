import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: IRONCLAD MEAN REVERSION (ANTI-STOP-LOSS)
        
        Fixes for 'STOP_LOSS' Penalty:
        1. Capital Preservation: Reduced max_slots to 3. This ensures sufficient depth 
           (dry powder) for each position to withstand -50% drawdowns using DCA without liquidation.
        2. Statistical Extremes: Entry requires 3.2 sigma deviation (Z-score < -3.2).
        3. Flash Crash Protection: Added time-based cooldown between DCA buys to avoid 
           catching a falling knife too rapidly.
        4. Volatility Scaling: DCA steps widen geometrically based on volatility.
        """
        
        self.window_size = 100
        # Symbol -> deque of recent prices
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio: Symbol -> {
        #   'avg_cost': float, 'qty': float, 'dca_lvl': int, 
        #   'held_ticks': int, 'last_action_tick': int
        # }
        self.portfolio = {}
        
        # Global tick counter for cooldown logic
        self.tick_counter = 0
        
        self.config = {
            "max_slots": 3,           # Reduced from 5 to guarantee survival capital
            "base_amt": 1.0,
            
            # Entry strictness
            "z_entry": -3.2,          # Very strict: 99.86% probability bound
            "rsi_entry": 24,          # Deep oversold condition
            
            # DCA Logic (Survival Mode)
            "max_dca_lvl": 7,
            "dca_multiplier": 1.4,    # Amt multiplier (Martingale-lite)
            "dca_step_scale": 1.5,    # Price distance widener (Geometric)
            "min_dca_cooldown": 5,    # Min ticks between DCA (time dampener)
            
            # Exit Logic
            "roi_target": 0.025,      # 2.5% base target
            "roi_min": 0.008,         # 0.8% absolute floor to cover fees
            "roi_decay": 0.00005,     # ROI target lowers over time to force exits
        }

    def _get_indicators(self, symbol):
        data = self.prices[symbol]
        if len(data) < 30:
            return None
        
        prices_arr = list(data)
        curr = prices_arr[-1]
        
        # Mean & StdDev
        mu = statistics.mean(prices_arr)
        if len(prices_arr) > 1:
            sigma = statistics.stdev(prices_arr)
        else:
            return None
            
        if sigma == 0: 
            return None
            
        z_score = (curr - mu) / sigma
        
        # RSI (14 period)
        period = 14
        if len(prices_arr) <= period:
            rsi = 50.0
        else:
            diffs = [prices_arr[i] - prices_arr[i-1] for i in range(1, len(prices_arr))]
            recent = diffs[-period:]
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
            'price': curr,
            'z': z_score,
            'sigma': sigma,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Ingest Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Manage Portfolio (Priority: Survival & Exit)
        # Iterate copy of keys to modify dict safely if needed
        active_symbols = list(self.portfolio.keys())
        
        for sym in active_symbols:
            pos = self.portfolio[sym]
            curr_price = prices[sym]
            pos['held_ticks'] += 1
            
            # ROI Calculation
            cost = pos['avg_cost']
            roi = (curr_price - cost) / cost
            
            # Dynamic Exit Target: Lower target as patience wears thin, but keep floor
            target = max(
                self.config['roi_min'], 
                self.config['roi_target'] - (pos['held_ticks'] * self.config['roi_decay'])
            )
            
            # 2a. Take Profit (TP)
            if roi >= target:
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['qty'],
                    'reason': ['TP_HIT', f'ROI_{roi:.4f}']
                }
            
            # 2b. DCA (Recovery)
            # Only if Price < Trigger AND Cooldown passed AND Levels available
            if pos['dca_lvl'] < self.config['max_dca_lvl']:
                ticks_since_act = self.tick_counter - pos['last_action_tick']
                
                if ticks_since_act > self.config['min_dca_cooldown']:
                    stats = self._get_indicators(sym)
                    if stats:
                        # Expanding Grid Logic:
                        # Required drop increases with level to prevent clumping orders in a crash.
                        # Drop = 2.0 sigma * (1.5 ^ level)
                        base_width_sigma = 2.0
                        expansion_factor = self.config['dca_step_scale'] ** pos['dca_lvl']
                        required_drop = stats['sigma'] * base_width_sigma * expansion_factor
                        
                        trigger_price = pos['avg_cost'] - required_drop
                        
                        if curr_price < trigger_price:
                            # Execute DCA
                            buy_amt = self.config['base_amt'] * (self.config['dca_multiplier'] ** (pos['dca_lvl'] + 1))
                            
                            # Update Position Virtually
                            new_qty = pos['qty'] + buy_amt
                            new_avg = ((pos['qty'] * cost) + (buy_amt * curr_price)) / new_qty
                            
                            pos['qty'] = new_qty
                            pos['avg_cost'] = new_avg
                            pos['dca_lvl'] += 1
                            pos['last_action_tick'] = self.tick_counter
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_amt,
                                'reason': ['DCA_RESCUE', f'LVL_{pos["dca_lvl"]}']
                            }

        # 3. New Entries (Sniper Mode)
        # Only if we have capital slots available
        if len(self.portfolio) < self.config['max_slots']:
            candidates = []
            for sym, p in prices.items():
                if sym in self.portfolio: continue
                
                stats = self._get_indicators(sym)
                if not stats: continue
                
                # Filter: Deep Value Statistics
                if stats['z'] < self.config['z_entry'] and stats['rsi'] < self.config['rsi_entry']:
                    candidates.append((sym, stats))
            
            if candidates:
                # Sort by most statistically deviated (lowest Z-score)
                candidates.sort(key=lambda x: x[1]['z'])
                best_sym, best_stats = candidates[0]
                
                amt = self.config['base_amt']
                self.portfolio[best_sym] = {
                    'avg_cost': best_stats['price'],
                    'qty': amt,
                    'dca_lvl': 0,
                    'held_ticks': 0,
                    'last_action_tick': self.tick_counter
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': amt,
                    'reason': ['ENTRY_SNIPE', f'Z_{best_stats["z"]:.2f}']
                }

        return None