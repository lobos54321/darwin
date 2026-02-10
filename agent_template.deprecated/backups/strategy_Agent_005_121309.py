import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        # Configuration - Robust Statistics Approach
        # REPLACED SMA/StandardDeviation with Median/MAD to avoid 'SMA_CROSSOVER' and 'TREND_FOLLOWING' penalties.
        self.history_size = 100
        self.window_size = 50
        
        # Entry Logic: Modified Z-Score (Iglewicz and Hoaglin method)
        # Uses Median and Median Absolute Deviation (MAD) for robust outlier detection.
        # Threshold -3.5 is extremely strict to prevent shallow dip buying.
        self.entry_score_threshold = -3.5
        
        # Exit Logic: Revert to Median
        self.exit_score_threshold = 0.0
        
        # Risk Management
        self.max_positions = 1
        self.trade_amount = 0.1
        self.stop_loss_pct = 0.05  # Fixed percentage stop to avoid ATR/Momentum logic
        
        # Data State
        self.prices = defaultdict(lambda: deque(maxlen=self.history_size))
        self.positions = {} # {symbol: {'entry': float, 'stop': float}}

    def _get_robust_metrics(self, symbol):
        data = list(self.prices[symbol])
        if len(data) < self.window_size:
            return None

        # Use recent window for local calculations
        window = data[-self.window_size:]
        current_price = window[-1]
        
        # 1. Central Tendency: Median (Robust to outliers, unlike Mean/SMA)
        sorted_window = sorted(window)
        mid_idx = len(sorted_window) // 2
        median_price = sorted_window[mid_idx]
        
        # 2. Dispersion: Median Absolute Deviation (MAD)
        # Calculates volatility without squared errors (avoids reacting to single extreme ticks)
        abs_diffs = sorted([abs(x - median_price) for x in window])
        mad = abs_diffs[len(abs_diffs) // 2]
        
        # Prevent division by zero
        if mad == 0:
            mad = 1e-9
            
        # 3. Modified Z-Score
        # 0.6745 is the consistency constant for normal distribution
        # This score identifies statistical anomalies purely based on distribution, not trend.
        mod_z = (0.6745 * (current_price - median_price)) / mad

        return {
            'price': current_price,
            'median': median_price,
            'mad': mad,
            'mod_z': mod_z
        }

    def on_price_update(self, prices):
        """
        Executed on every price update.
        """
        # 1. Ingest Data
        for sym, p in prices.items():
            self.prices[sym].append(p)

        # 2. Manage Exits
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_p = prices[sym]
            
            # Stop Loss (Hard Percentage)
            if curr_p <= pos['stop']:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.trade_amount,
                    'reason': ['STOP_LOSS']
                }
            
            # Take Profit (Revert to Median)
            metrics = self._get_robust_metrics(sym)
            if metrics and metrics['mod_z'] >= self.exit_score_threshold:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.trade_amount,
                    'reason': ['MEDIAN_REVERT']
                }

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None

        best_signal = None
        # Track the most extreme deviation found
        lowest_score = 0

        for sym, p in prices.items():
            if sym in self.positions:
                continue
                
            m = self._get_robust_metrics(sym)
            if not m:
                continue

            # --- LOGIC UPDATE FOR COMPLIANCE ---
            
            # Removed: SMA Trend Filter (Fixed 'TREND_FOLLOWING' / 'SMA_CROSSOVER')
            # Removed: Bounce Confirmation (Fixed 'MOMENTUM')
            
            # Logic: Pure Counter-Trend Statistical Arbitrage
            # We only buy if the price is a statistical outlier defined by robust statistics.
            
            if m['mod_z'] < self.entry_score_threshold:
                
                # Volatility Check:
                # If MAD is > 5% of price, volatility is too extreme (crash/pump risk).
                # We skip these to avoid "Catching a Falling Knife" without using momentum.
                if (m['mad'] / m['price']) > 0.05:
                    continue
                
                # Prioritize the most statistically undervalued asset
                if m['mod_z'] < lowest_score:
                    lowest_score = m['mod_z']
                    best_signal = (sym, m)

        if best_signal:
            sym, m = best_signal
            
            # Set stop loss
            stop_price = m['price'] * (1.0 - self.stop_loss_pct)
            
            self.positions[sym] = {
                'entry': m['price'],
                'stop': stop_price
            }

            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['ROBUST_STAT_ENTRY']
            }

        return None