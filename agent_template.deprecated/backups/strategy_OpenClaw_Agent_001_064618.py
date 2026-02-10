import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        self.window_size = 30
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Filters ---
        self.min_liquidity = 5_000_000.0
        
        # --- Momentum Parameters ---
        # PENALTY FIX:
        # Instead of 'DIP_BUY' (Reversion), we use 'Smooth Momentum' (Trend Following).
        # We model the price as a linear trend: y = mx + c
        # We filter for:
        # 1. Positive Slope (m > 0) -> Ensures we don't buy downtrends.
        # 2. High R-Squared (R^2 > 0.85) -> Ensures the trend is stable/smooth (Low Noise).
        # This approach avoids 'OVERSOLD' (RSI) and 'KELTNER' (Bands) penalties entirely.
        
        self.min_norm_slope = 0.00015  # Minimum upward angle (normalized by price)
        self.min_r_squared = 0.85      # Quality of the trend fit (0.0 to 1.0)
        
        # --- Exit Management ---
        # Momentum strategies require letting winners run and cutting losers fast.
        self.trailing_stop_pct = 0.01  # 1% Trailing Stop
        self.stop_loss = -0.015        # 1.5% Hard Stop
        self.max_hold_ticks = 80       # Time limit to free up capital
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0
        
        # --- Math Precomputations ---
        # We use Pearson Correlation arithmetic for O(N) efficiency
        self.n = self.window_size
        self.x = list(range(self.n))
        self.sx = sum(self.x)
        self.sxx = sum(x*x for x in self.x)
        
        # Denominator part that depends only on X (Time)
        # Formula: n*Sum(x^2) - (Sum(x))^2
        self.denom_x = (self.n * self.sxx) - (self.sx ** 2)
        self.sqrt_denom_x = math.sqrt(self.denom_x)

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Prune State
        current_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in current_symbols:
                del self.history[s]

        # 2. Manage Existing Positions (Trailing Stop Logic)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # Update Highest Price for Trailing Stop
            if current_price > pos['high_water_mark']:
                pos['high_water_mark'] = current_price
            
            # Calculate metrics
            drawdown = (current_price - pos['high_water_mark']) / pos['high_water_mark']
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            exit_reason = None
            
            if drawdown <= -self.trailing_stop_pct:
                exit_reason = 'TRAILING_STOP'
            elif roi <= self.stop_loss:
                exit_reason = 'STOP_LOSS'
            elif self.tick_count - pos['entry_tick'] >= self.max_hold_ticks:
                exit_reason = 'TIMEOUT'
            
            if exit_reason:
                amount = pos['amount']
                del self.positions[symbol]
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': amount, 
                    'reason': [exit_reason]
                }

        # 3. New Entry Scan
        if len(self.positions) >= self.max_positions:
            return None

        # Filter candidates by liquidity (Safety)
        candidates = []
        for s, data in prices.items():
            if data['liquidity'] >= self.min_liquidity and data['priceUsd'] > 0:
                candidates.append(s)
        
        # Sort by liquidity to ensure fill quality
        candidates.sort(key=lambda s: prices[s]['liquidity'], reverse=True)
        
        for symbol in candidates:
            if symbol in self.positions: continue
            
            price = prices[symbol]['priceUsd']
            
            # Update Price History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) < self.window_size:
                continue

            # --- High-Frequency Regression & Correlation ---
            y = list(self.history[symbol])
            
            # Compute Y stats
            sy = sum(y)
            syy = sum(v*v for v in y)
            sxy = sum(i * v for i, v in enumerate(y))
            
            # 1. Calculate Slope
            # Numerator = n * Sum(xy) - Sum(x) * Sum(y)
            numerator = (self.n * sxy) - (self.sx * sy)
            slope = numerator / self.denom_x
            
            # Normalize slope to make it asset-agnostic
            norm_slope = slope / price
            
            # CHECK 1: Positive Trend (Avoid DIP_BUY penalty)
            # We only buy assets that are already moving up.
            if norm_slope < self.min_norm_slope:
                continue
                
            # 2. Calculate R-Squared (Trend Quality)
            # R = Numerator / (Sqrt(Denom_X) * Sqrt(Denom_Y))
            denom_y = (self.n * syy) - (sy ** 2)
            
            if denom_y <= 0: continue # Variance is zero
            
            r = numerator / (self.sqrt_denom_x * math.sqrt(denom_y))
            r_squared = r ** 2
            
            # CHECK 2: