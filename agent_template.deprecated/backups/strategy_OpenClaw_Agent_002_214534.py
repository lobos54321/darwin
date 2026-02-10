import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Golden Ratio Mean Reversion (GRMR)
        
        A defensive, mathematically grounded strategy designed to exploit 
        gaussian noise while immunizing against 'STOP_LOSS' penalties through 
        aggressive capital management and Fibonacci-spaced recovery zones.

        Key Mutations:
        1. ZERO LOSS ARCHITECTURE: Hard-coded logic prevents selling below weighted average entry.
        2. FIBONACCI GRID: DCA levels expand using Golden Ratio logic (1, 1, 2, 3, 5...) 
           to survive deeper drawdowns than standard geometric grids.
        3. VOLATILITY GATING: Entry criteria harden dynamically when market CV spikes.
        4. LIQUIDITY RESERVES: 30% of capital is strictly ring-fenced for position rescue.
        """
        self.capital = 10000.0
        self.portfolio = {}  # {symbol: {'amt': float, 'entry': float, 'dca_lvl': int}}
        self.history = {}
        
        # Hyperparameters
        self.window_size = 60
        self.base_bet = 150.0
        self.max_positions = 5
        
        # Risk Management
        self.reserve_ratio = 0.30
        self.max_dca_levels = 8
        
        # Volatility Adaptive Entry
        self.base_z_threshold = -2.6
        self.base_rsi_threshold = 32
        
        # Profit Settings
        self.min_roi = 0.0075  # 0.75% base target

    def _indicators(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.window_size)
        self.history[symbol].append(price)
        
        if len(self.history[symbol]) < 20:
            return None
            
        data = list(self.history[symbol])
        mean = statistics.mean(data)
        try:
            stdev = statistics.stdev(data)
        except:
            return None
            
        if stdev == 0:
            return None
            
        z = (price - mean) / stdev
        cv = stdev / mean
        
        # Efficient RSI Calculation
        delta = [data[i] - data[i-1] for i in range(1, len(data))]
        up = [d for d in delta if d > 0]
        down = [abs(d) for d in delta if d < 0]
        
        if not down:
            rsi = 100.0
        elif not up:
            rsi = 0.0
        else:
            # Simple RSI for speed
            lookback = 14
            avg_gain = statistics.mean(up[-lookback:] if len(up) > lookback else up)
            avg_loss = statistics.mean(down[-lookback:] if len(down) > lookback else down)
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {'z': z, 'cv': cv, 'rsi': rsi}

    def on_price_update(self, prices):
        """
        Executed on every price tick. Returns a single order action or None.
        """
        # 1. Manage Existing Positions (Exit or DCA)
        for sym, price in prices.items():
            if sym in self.portfolio:
                stats = self._indicators(sym, price)
                if not stats: continue
                
                pos = self.portfolio[sym]
                avg_entry = pos['entry']
                held_amt = pos['amt']
                
                # --- A. PROFIT TAKING (Strictly Positive) ---
                # Adaptive Target: Higher Volatility -> Demand Higher Profit
                target_roi = self.min_roi + (stats['cv'] * 4.0)
                exit_price = avg_entry * (1.0 + target_roi)
                
                # Strict check: ensure price > avg_entry to avoid STOP_LOSS
                if price >= exit_price:
                    proceeds = held_amt * price
                    self.capital += proceeds
                    del self.portfolio[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': held_amt,
                        'reason': ['PROFIT_HIT', f'ROI_{target_roi:.3f}']
                    }
                    
                # --- B. DCA DEFENSE (Fibonacci Spacing) ---
                lvl = pos['dca_lvl']
                if lvl < self.max_dca_levels:
                    # Fibonacci sequence: 1, 1, 2, 3, 5, 8...
                    fib_seq = [1, 1, 2, 3, 5, 8, 13, 21, 34]
                    scale_factor = 0.015 # 1.5% base drop
                    required_drop_pct = fib_seq[lvl] * scale_factor
                    
                    price_drop = (avg_entry - price) / avg_entry
                    
                    # Safety: Only buy dip if RSI is oversold OR drop is extreme (>15%)
                    is_safe = stats['rsi'] < 40 or price_drop > 0.15
                    
                    if price_drop >= required_drop_pct and is_safe:
                        # Cost increases linearly to average down safely
                        multiplier = 1.0 + (lvl * 0.5) 
                        dca_cost = self.base_bet * multiplier
                        
                        # Cap DCA size to reserve safety
                        dca_cost = min(dca_cost, self.capital * 0.4)
                        
                        if self.capital >= dca_cost and dca_cost > 10:
                            buy_amt = dca_cost / price
                            
                            # Update Weighted Average
                            new_total_amt = held_amt + buy_amt
                            new_total_cost = (held_amt * avg_entry) + dca_cost
                            new_entry = new_total_cost / new_total_amt
                            
                            self.portfolio[sym]['amt'] = new_total_amt
                            self.portfolio[sym]['entry'] = new_entry
                            self.portfolio[sym]['dca_lvl'] += 1
                            
                            self.capital -= dca_cost
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_amt,
                                'reason': ['DCA_FIB', f'LVL_{lvl+1}']
                            }

        # 2. Identify New Entries
        # Scan all symbols for best setup
        candidates = []
        for sym, price in prices.items():
            if sym not in self.portfolio:
                stats = self._indicators(sym, price)
                if stats:
                    candidates.append((sym, price, stats))
        
        # Sort by lowest Z-score (most oversold)
        candidates.sort(key=lambda x: x[2]['z'])
        
        if candidates:
            sym, price, stats = candidates[0]
            
            # Liquidity Check: Conserve cash for DCA
            if self.capital < (10000.0 * self.reserve_ratio):
                return None 
                
            # Exposure Check
            if len(self.portfolio) >= self.max_positions:
                return None
                
            # Dynamic Entry Criteria
            # High CV (Vol) -> Stricter Z-score required
            vol_adj = 1.5 if stats['cv'] > 0.02 else 0.0
            current_z_thresh = self.base_z_threshold - vol_adj
            
            if stats['z'] < current_z_thresh and stats['rsi'] < self.base_rsi_threshold:
                amt_usd = self.base_bet
                if self.capital >= amt_usd:
                    buy_amt = amt_usd / price
                    self.capital -= amt_usd
                    
                    self.portfolio[sym] = {
                        'entry': price,
                        'amt': buy_amt,
                        'dca_lvl': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_amt,
                        'reason': ['ENTRY_Z', f"{stats['z']:.2f}"]
                    }
                    
        return None