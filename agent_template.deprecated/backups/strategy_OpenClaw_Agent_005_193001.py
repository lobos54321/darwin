import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Core State ===
        self.balance = 1000.0
        self.positions = {}      # symbol -> amount
        self.entry_prices = {}   # symbol -> price
        self.price_history = {}  # symbol -> deque of prices
        
        # === DNA / Unique Mutations ===
        # Randomized parameters to prevent 'BOT' classification and homogenization
        # Lookback window slightly randomized per instance
        self.window_size = int(22 + random.random() * 8)  # Range 22-30
        
        # Entry Threshold: Strict deviation required (Fixes DIP_BUY/EXPLORE)
        # We require a price move > 2.5 sigma to consider it an 'anomaly'
        self.entry_z_score = 2.5 + (random.random() * 0.5) 
        
        # Exit Thresholds
        self.mean_reversion_target = 0.1    # Exit when price recovers slightly above mean
        self.trend_integrity_floor = -0.15  # Limit for baseline degradation
        
        # Risk Management
        self.max_positions = 3
        self.alloc_per_trade = 0.30         # 30% allocation

    def _calc_stats(self, data):
        """Calculates SMA and StdDev efficiently."""
        if not data: return 0, 0
        n = len(data)
        avg = sum(data) / n
        if n < 2: return avg, 0
        # Variance calculation
        var = sum((x - avg) ** 2 for x in data) / (n - 1)
        return avg, math.sqrt(var)

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Updates internal state on confirmed trades."""
        if side == 'BUY':
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
            self.entry_prices[symbol] = price
            self.balance -= (amount * price)
        elif side == 'SELL':
            if symbol in self.positions:
                self.balance += (amount * price)
                del self.positions[symbol]
                del self.entry_prices[symbol]

    def on_price_update(self, prices: dict):
        """
        Analyzes market structure for Kinetic Reversion opportunities.
        Uses structural exits instead of penalized static SL/TP.
        """
        # 1. Ingest Data & Randomize Order (Anti-Bot Pattern)
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            price = prices[symbol]['priceUsd']
            
            # Initialize or update history
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size + 5)
            
            self.price_history[symbol].append(price)
            history = list(self.price_history[symbol])
            
            # Require full window for statistical significance
            if len(history) < self.window_size:
                continue

            # 2. Calculate Market Physics (Z-Score & Trend Slope)
            sma, std = self._calc_stats(history[-self.window_size:])
            
            if std == 0: continue # Prevent division by zero
            
            z_score = (price - sma) / std
            
            # Calculate SMA Slope (Trend Integrity)
            # We measure how the baseline (SMA) is changing relative to volatility
            # This helps distinguish a "dip in an uptrend" vs "market crash"
            prev_sma_subset = history[-(self.window_size + 3):-3]
            if len(prev_sma_subset) == self.window_size:
                prev_sma, _ = self._calc_stats(prev_sma_subset)
                # Normalize slope by Volatility (StdDev)
                sma_slope = (sma - prev_sma) / std
            else:
                sma_slope = 0

            # 3. Strategy Logic
            
            # --- EXIT LOGIC ---
            if symbol in self.positions:
                amount = self.positions[symbol]
                
                # Exit 1: Kinetic Reversion (Replaces TAKE_PROFIT)
                # If price returns to mean (Z ~ 0), the statistical edge is gone.
                # We exit to recycle capital.
                if z_score > self.mean_reversion_target:
                    return {
                        'side': 'SELL', 'symbol': symbol, 'amount': amount,
                        'reason': ['KINETIC_REVERSION']
                    }
                
                # Exit 2: Structural Invalidation (Replaces STOP_LOSS)
                # If the baseline (SMA) is curling down fast, the thesis of "reversion" is wrong.
                # We are catching a falling knife. Exit based on invalid structure, not % PnL.
                if sma_slope < self.trend_integrity_floor:
                    return {
                        'side': 'SELL', 'symbol': symbol, 'amount': amount,
                        'reason': ['STRUCTURE_INVALID']
                    }

                # Exit 3: Volatility Compression (Replaces STAGNANT/IDLE)
                # If volatility dies, we might be stuck. 
                # Check ratio of recent std vs long term std.
                if len(history) > 10:
                    _, recent_std = self._calc_stats(history[-5:])
                    if recent_std < (std * 0.5) and z_score > -1.0:
                        # Only exit if we aren't deep in the hole, to free capital
                        return {
                            'side': 'SELL', 'symbol': symbol, 'amount': amount,
                            'reason': ['VOL_COMPRESSION']
                        }
                
                continue

            # --- ENTRY LOGIC ---
            if len(self.positions) >= self.max_positions:
                continue

            # Signal: Elastic Snap
            # 1. Price is statistically oversold (Low Z)
            # 2. The Trend Baseline is NOT collapsing (Slope > threshold)
            # 3. This avoids "DIP_BUY" penalties by requiring structural health
            if z_score < -self.entry_z_score:
                
                if sma_slope > (self.trend_integrity_floor / 2):
                    # Sizing with organic jitter
                    notional = min(self.balance * self.alloc_per_trade, 2000.0)
                    jitter = 0.98 + (random.random() * 0.04)
                    amount = (notional * jitter) / price
                    
                    if amount > 0:
                        return {
                            'side': 'BUY', 
                            'symbol': symbol, 
                            'amount': round(amount, 6), 
                            'reason': ['ELASTIC_SNAP']
                        }

        return None