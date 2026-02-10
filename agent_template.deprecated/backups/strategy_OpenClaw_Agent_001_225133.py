import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive EMA Mean Reversion with Trend Stability Gate
        
        Improvements & Fixes:
        1. LR_RESIDUAL Fix: 
           - Replaced simple statistics with an Exponential Moving Average (EMA) baseline.
           - This avoids the lag and 'residual' errors associated with static means or linear regression
             during sharp parabolic moves.
           
        2. Z:-3.93 Penalty Fix (Falling Knife Protection):
           - Implemented a 'Stability Gate' (EMA Slope).
           - Even if the Z-score indicates a 'Buy' (-3.93), we REJECT the trade if the EMA itself
             is falling rapidly (slope < -0.0002). This filters out crashes where the "Mean" is collapsing.
           - Tightened the 'Panic Floor' to -4.5 to avoid extreme outliers.
           
        3. Profitability:
           - Dynamic volatility filter: We only trade assets with sufficient volatility to justify the spread.
           - Stricter RSI limit (25) combined with the Stability Gate ensures we buy 'Stable Dips' not 'Crashes'.
        """
        self.window_size = 50
        self.min_liquidity = 10000000.0  # 10M Min Liquidity
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # EMA Parameters
        self.ema_period = 40
        self.alpha = 2 / (self.ema_period + 1)
        
        # Filters / Thresholds
        self.z_entry_threshold = -2.6    # Entry signal
        self.z_panic_floor = -4.5        # Crash protection (Don't buy below this)
        self.rsi_threshold = 25          # Oversold condition
        self.ema_slope_threshold = -0.0002 # Stability Gate: EMA cannot be falling faster than this per tick
        self.min_volatility = 0.003      # 0.3% Min Volatility required
        
        # Exits
        self.stop_loss_pct = 0.04        # 4% Stop Loss
        self.max_hold_ticks = 30         # Time decay exit
        
        # State
        self.history = {}
        self.positions = {}
        self.tick_count = 0

    def calculate_indicators(self, symbol, current_price):
        if symbol not in self.history or len(self.history[symbol]) < self.window_size:
            return None
            
        prices = list(self.history[symbol])
        
        # 1. Volatility (Standard Deviation)
        # Using standard deviation of the window to normalize the deviation (Z-Score)
        try:
            stdev = statistics.stdev(prices)
        except:
            return None
            
        if stdev == 0:
            return None

        # 2. EMA Calculation (State-independent reconstruction for robustness)
        # EMA_t = Price_t * alpha + EMA_t-1 * (1-alpha)
        ema = prices[0]
        for p in prices[1:]:
            ema = (p * self.alpha) + (ema * (1 - self.alpha))
            
        # 3. EMA Slope (Trend Stability)
        # We need the previous tick's EMA to determine if the baseline is crashing
        ema_prev = prices[0]
        # Iterate up to the second-to-last item to get EMA_{t-1}
        for p in prices[1:-1]:
            ema_prev = (p * self.alpha) + (ema_prev * (1 - self.alpha))
            
        slope = (ema - ema_prev) / ema_prev if ema_prev > 0 else 0
        
        # 4. Z-Score (Price deviation from EMA)
        z_score = (current_price - ema) / stdev
        
        # 5. RSI (14 period)
        rsi = 50
        period = 14
        if len(prices) > period:
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            recent = deltas[-period:]
            gains = [d for d in recent if d > 0]
            losses = [-d for d in recent if d < 0]
            
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            
            if avg_loss == 0:
                rsi = 100
            elif avg_gain == 0:
                rsi = 0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                
        return {
            'z': z_score,
            'rsi': rsi,
            'ema': ema,
            'slope': slope,
            'stdev': stdev
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # --- 1. Update History ---
        active_candidates = []
        for symbol, data in prices.items():
            if data['liquidity'] < self.min_liquidity:
                continue
                
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(data['priceUsd'])
            
            if len(self.history[symbol]) == self.window_size:
                active_candidates.append(symbol)
                
        # --- 2. Manage Exits ---
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            stats = self.calculate_indicators(symbol, current_price)
            
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            action = None
            reason = None
            
            # Stop Loss
            if roi < -self.stop_loss_pct:
                action = 'SELL'
                reason = 'STOP_LOSS'
            
            # Timeout
            elif (self.tick_count - pos['entry_tick']) > self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIMEOUT'
            
            # Take Profit: Reverted to EMA (Fair Value)
            elif stats and current_price >= stats['ema']:
                action = 'SELL'
                reason = 'EMA_REVERTED'
                
            if action == 'SELL':
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': [reason]
                }

        # --- 3. Manage Entries ---
        if len(self.positions) >= self.max_positions:
            return None
            
        potential_buys = []
        
        for symbol in active_candidates:
            if symbol in self.positions:
                continue
                
            current_price = prices[symbol]['priceUsd']
            stats = self.calculate_indicators(symbol, current_price)
            
            if not stats:
                continue
                
            # --- FILTER LOGIC ---
            
            # 1. Volatility Gate
            # Avoid flat lines where Z-scores are noise
            if (stats['stdev'] / current_price) < self.min_volatility:
                continue
            
            # 2. Z-Score Window
            # Must be a dip (<-2.6) but not a black swan (>-4.5)
            if stats['z'] > self.z_entry_threshold or stats['z'] < self.z_panic_floor:
                continue
                
            # 3. Stability Gate (CRITICAL FIX for Z:-3.93)
            # If the EMA is angling down sharply, the trend is broken. Do not buy.
            if stats['slope'] < self.ema_slope_threshold:
                continue
                
            # 4. Momentum Gate
            if stats['rsi'] > self.rsi_threshold:
                continue
                
            # 5. Micro-Reversal Confirmation
            # Price must be ticking up from the absolute bottom of the window logic
            prev_price = self.history[symbol][-2]
            if current_price <= prev_price:
                continue
                
            # If all passed, it's a valid candidate
            # We weight by how "extreme" the Z is (deeper is usually better if