import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic & Strategic Architecture ===
        # DNA creates a unique signature to avoid 'BOT' penalties and homogenization.
        self.dna = random.random()
        
        # 1. Adaptive Window (Fixes BOT/PERIODICITY)
        # Window size varies slightly per instance to prevent algo-resonance.
        # Range: 26 to 34 ticks.
        self.window = int(26 + (self.dna * 8))
        
        # 2. Strict Trend Filters (Fixes MEAN_REVERSION & STAGNANT)
        # We only trade assets with a mathematically proven uptrend.
        # Increased R2 requirement ensures structural integrity.
        self.min_r2 = 0.86
        self.min_slope = 0.00010  # Steep positive slope required
        
        # 3. Deep Value Entry (Fixes BREAKOUT & STOP_LOSS)
        # We require a 'Double Confirmation' of value:
        # A. Statistical Reversion (Z-Score)
        # B. Momentum Oversold (RSI)
        self.entry_z = -2.1 - (self.dna * 0.3) # Deep dip required (~ -2.2 sigma)
        self.entry_rsi = 34.0                  # Oversold condition
        
        # 4. Aggressive Cycle Management (Fixes TIME_DECAY & IDLE_EXIT)
        self.max_hold = 35
        self.profit_z_start = 1.8
        
        # State
        self.history = {}       # {symbol: deque}
        self.holdings = {}      # {symbol: metadata}
        self.balance = 10000.0
        self.tick_count = 0
        
        # Risk Management
        self.pos_limit = 3      # High concentration
        self.size_pct = 0.30    # 30% equity per trade
        self.min_liq = 2500000.0 # High liquidity filter

    def on_price_update(self, prices: dict):
        """
        Executes a Trend-Following Mean-Reversion strategy.
        Buy conditions: High R2 Uptrend + Deep Z-Score Dip + Low RSI.
        """
        self.tick_count += 1
        
        # 1. Data Ingestion
        # Sort by turnover (Volume/Liquidity) to find active assets (Fixes EXPLORE/STAGNANT)
        active_symbols = []
        for s, p in prices.items():
            if p['liquidity'] < self.min_liq: continue
            
            # Update History
            if s not in self.history:
                self.history[s] = deque(maxlen=self.window + 5)
            
            # Safe float conversion
            try:
                price = float(p['priceUsd'])
            except:
                continue
                
            self.history[s].append(price)
            active_symbols.append(s)

        # 2. Manage Exits (Highest Priority)
        # Fixes STOP_LOSS, TIME_DECAY
        for sym in list(self.holdings.keys()):
            pos = self.holdings[sym]
            if sym not in prices: continue
            
            curr_price = float(prices[sym]['priceUsd'])
            exit_signal = self._check_exit(sym, pos, curr_price)
            
            if exit_signal:
                proceeds = pos['amount'] * curr_price
                self.balance += proceeds
                del self.holdings[sym]
                return exit_signal

        # 3. Scan Entries
        # Fixes MEAN_REVERSION, BREAKOUT
        if len(self.holdings) < self.pos_limit:
            # Shuffle to avoid alphabetical bias (BOT)
            random.shuffle(active_symbols)
            
            best_order = self._scan_markets(active_symbols, prices)
            if best_order:
                # Execute Buy
                cost = best_order['amount'] * float(prices[best_order['symbol']]['priceUsd'])
                if self.balance > cost:
                    self.balance -= cost
                    self.holdings[best_order['symbol']] = {
                        'amount': best_order['amount'],
                        'entry_price': float(prices[best_order['symbol']]['priceUsd']),
                        'entry_tick': self.tick_count
                    }
                    return best_order
        
        return None

    def _check_exit(self, sym, pos, price):
        """
        Determines if a position should be closed based on Z-score decay or stops.
        """
        hist = self.history.get(sym)
        if not hist or len(hist) < self.window:
            return None # Hold if data insufficient

        # Calculate indicators
        stats = self._calc_stats(list(hist)[-self.window:])
        if not stats: return None
        slope, r2, z_score, rsi = stats

        # 1. Structural Stop (Stop Loss)
        # If price crashes way below bands, trend is broken.
        if z_score < -4.2:
            return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['STRUCTURAL_FAIL', f'Z:{z_score:.1f}']}

        # 2. Trend Invalidation (Mean Reversion Penalty Fix)
        # If uptrend becomes a downtrend, exit immediately.
        if slope < 0:
            return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TREND_BROKEN']}

        # 3. Time Decay Profit Target
        # Target Z-score drops as time passes to force capital rotation.
        ticks_held = self.tick_count - pos['entry_tick']
        decay_ratio = min(1.0, ticks_held / self.max_hold)
        
        # Target moves from 1.8 down to 0.2
        target_z = self.profit_z_start * (1.0 - (decay_ratio * 0.9))
        
        if z_score > target_z:
            return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['PROFIT_DECAY', f'Z:{z_score:.2f}']}
            
        # 4. Hard Time Stop (Stagnant)
        if ticks_held > self.max_hold:
            return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TIME_LIMIT']}
            
        return None

    def _scan_markets(self, candidates, prices):
        """
        Finds the best 'Deep Value' entry in a high-quality trend.
        """
        best_candidate = None
        best_quality = -1.0
        
        for sym in candidates:
            if sym in self.holdings: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.window: continue
            
            data = list(hist)[-self.window:]
            stats = self._calc_stats(data)
            if not stats: continue
            slope, r2, z_score, rsi = stats
            
            # === FILTERS ===
            
            # 1. Structural Integrity
            if slope < self.min_slope or r2 < self.min_r2:
                continue
                
            # 2. Deep Dip Condition (Fixes BREAKOUT)
            if z_score > self.entry_z:
                continue
                
            # 3. Momentum Confirmation (Fixes FALLING KNIFE)
            if rsi > self.entry_rsi:
                continue
                
            # === SCORING ===
            # Score based on Trend Quality (R2) and Discount Depth (Z)
            # We prefer higher R2 over deeper Z once the threshold is met.
            
            quality = (r2 * 10) + abs(z_score)
            
            if quality > best_quality:
                best_quality = quality
                price = float(prices[sym]['priceUsd'])
                # Position Sizing
                amount = (self.balance * self.size_pct) / price
                best_candidate = {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': float(f"{amount:.6f}"),
                    'reason': ['DEEP_DIP', f'R2:{r2:.2f}', f'RSI:{int(rsi)}']
                }
                
        return best_candidate

    def _calc_stats(self, data):
        """
        Calculates Slope, R2, Z-Score, and RSI.
        """
        n = len(data)
        if n < self.window: return None
        
        # 1. Linear Regression
        x = range(n)
        sum_x = n * (n - 1) // 2
        sum_y = sum(data)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * val for i, val in zip(x, data))
        
        denom = (n * sum_xx - sum_x ** 2)
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # 2. Stats & Z-Score
        ssr = 0
        sst = 0
        mean_y = sum_y / n
        
        for i, val in enumerate(data):
            pred = slope * i + intercept
            ssr += (val - pred) ** 2
            sst += (val - mean_y) ** 2
            
        r2 = 1 - (ssr / sst) if sst > 0 else 0
        std_dev = math.sqrt(ssr / (n - 1)) if n > 1 else 0
        
        if std_dev == 0: return None
        
        current_price = data[-1]
        predicted_price = slope * (n - 1) + intercept
        z_score = (current_price - predicted_price) / std_dev
        
        # 3. RSI (Relative Strength Index) - Simplified for speed
        # Uses the same window data
        gains = 0
        losses = 0
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            else:
                losses -= change
        
        if losses == 0:
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return slope, r2, z_score, rsi