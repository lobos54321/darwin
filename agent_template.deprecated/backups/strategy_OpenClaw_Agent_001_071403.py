import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy Configuration ---
        self.window_size = 25  # Lookback window for regression
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # --- Filters ---
        self.min_liquidity = 6_000_000.0
        
        # --- Momentum Parameters (Log-Linear Regression) ---
        # To strictly avoid 'DIP_BUY' and 'OVERSOLD' penalties:
        # 1. We operate on Log(Price) to normalize returns.
        # 2. We require a steep positive slope (Momentum).
        # 3. We require high R-squared (Smoothness).
        # 4. We require positive Z-Score (Breakout/Strength verification).
        
        self.min_log_slope = 0.00025   # Min slope of log-price regression line
        self.min_r_squared = 0.88      # Minimum fit quality
        self.min_z_score = 0.5         # Price must be > 0.5 std deviations ABOVE mean (Anti-Dip)
        
        # --- Exit Management ---
        self.trailing_stop_pct = 0.015 # 1.5% Trailing Stop
        self.hard_stop = -0.02         # 2% Hard Stop
        self.max_hold_ticks = 50       # Rotate capital frequently
        
        # --- State ---
        self.history = {}
        self.positions = {}
        self.tick_count = 0
        
        # --- Math Precomputations ---
        self.n = self.window_size
        self.x = list(range(self.n))
        self.sum_x = sum(self.x)
        self.sum_x_sq = sum(x*x for x in self.x)
        # Denominator for slope: n*Sum(x^2) - (Sum(x))^2
        self.denom_x = (self.n * self.sum_x_sq) - (self.sum_x ** 2)
        self.sqrt_denom_x = math.sqrt(self.denom_x)

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Prune State for symbols no longer in feed
        current_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in current_symbols:
                del self.history[s]

        # 2. Manage Existing Positions
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # Update High Water Mark
            if current_price > pos['high_water_mark']:
                pos['high_water_mark'] = current_price
            
            # Calculate PnL stats
            drawdown = (current_price - pos['high_water_mark']) / pos['high_water_mark']
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            exit_reason = None
            
            # Strict exits to protect capital
            if drawdown <= -self.trailing_stop_pct:
                exit_reason = 'TRAILING_STOP'
            elif roi <= self.hard_stop:
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

        # Filter candidates by liquidity
        candidates = []
        for s, data in prices.items():
            if data['liquidity'] >= self.min_liquidity and data['priceUsd'] > 0:
                candidates.append(s)
        
        # Sort by 24h Price Change (Focus on leaders, not laggards)
        candidates.sort(key=lambda s: prices[s]['priceChange24h'], reverse=True)
        
        for symbol in candidates:
            if symbol in self.positions: continue
            
            # Use Log Price for geometric regression
            price = prices[symbol]['priceUsd']
            log_price = math.log(price)
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(log_price)
            
            if len(self.history[symbol]) < self.window_size:
                continue

            # --- Regression Math ---
            y = list(self.history[symbol])
            sum_y = sum(y)
            sum_y_sq = sum(v*v for v in y)
            sum_xy = sum(i * v for i, v in enumerate(y))
            
            # Calculate Slope (Alpha)
            numerator = (self.n * sum_xy) - (self.sum_x * sum_y)
            slope = numerator / self.denom_x
            
            # Filter 1: Positive Momentum (Steepness)
            if slope < self.min_log_slope:
                continue
                
            # Calculate R-Squared (Quality of Fit)
            denom_y = (self.n * sum_y_sq) - (sum_y ** 2)
            if denom_y <= 1e-10: continue
            
            r_numerator = numerator # Same numerator for correlation
            r = r_numerator / (self.sqrt_denom_x * math.sqrt(denom_y))
            r_squared = r ** 2
            
            # Filter 2: Smooth Trend
            if r_squared < self.min_r_squared:
                continue
                
            # Filter 3: Z-Score (Anti-Dip / Breakout Confirmation)
            # We enforce that the current price is in the upper band of the window.
            # This explicitly prevents "Dip Buying" logic.
            mean = sum_y / self.n
            std_dev = math.sqrt(denom_y) / self.n # Simplified derivation
            
            if std_dev < 1e-10: continue
            
            z_score = (y[-1] - mean) / std_dev
            
            if z_score < self.min_z_score:
                continue
                
            # --- Execute Trade ---
            amount = self.trade_size_usd / price
            self.positions[symbol] = {
                'entry_price': price,
                'high_water_mark': price,
                'amount': amount,
                'entry_tick': self.tick_count
            }
            
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': amount,
                'reason': ['LOG_MOMENTUM', f'R2_{r_squared:.2f}']
            }
            
        return None