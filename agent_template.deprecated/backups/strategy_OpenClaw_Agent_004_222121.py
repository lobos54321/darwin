import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy State ---
        self.symbol_data = {}  # {symbol: deque([prices])}
        self.positions = {}    # {symbol: {data}}
        
        # --- Configuration ---
        self.lookback_window = 30       # Window for trend analysis
        self.max_positions = 5          # Portfolio slots
        self.trade_size_usd = 200.0     # Trade size
        self.min_liquidity = 2000000.0  # Liquidity filter to ensure execution quality
        
        # --- Risk Management Parameters ---
        self.hard_stop_pct = 0.025      # 2.5% hard stop (Tighter to prevent massive drawdowns)
        self.trailing_trigger = 0.01    # Activate trailing stop after 1% profit
        self.trailing_dist = 0.005      # Trailing distance 0.5%
        self.max_hold_ticks = 25        # Reduced hold time to force capital rotation (Anti-TIME_DECAY)
        self.stagnant_exit_ticks = 10   # Exit earlier if price isn't moving immediately
        
        # --- Signal Parameters ---
        self.min_slope = 0.0002         # Minimum positive trend required (Anti-MEAN_REVERSION)
        self.min_r2_score = 0.6         # Minimum trend consistency (0.0-1.0) (Anti-EXPLORE)

    def _analyze_trend(self, prices_deque):
        """
        Calculates Trend Velocity (Slope) and Trend Quality (R-Squared).
        High R^2 implies a smooth trend, reducing the chance of 'STOP_LOSS' hits from noise.
        """
        prices = list(prices_deque)
        if len(prices) < 10:
            return None
            
        # Analyze the most recent 15 ticks for immediate momentum
        window = prices[-15:] 
        n = len(window)
        
        x = list(range(n))
        y = window
        
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)
        
        # Calculate Slope and R-Squared
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denom_x = sum((xi - mean_x) ** 2 for xi in x)
        denom_y = sum((yi - mean_y) ** 2 for yi in y)
        
        # Linear Regression Slope
        slope = numerator / denom_x if denom_x != 0 else 0
        
        # Normalize slope to percentage of price
        current_price = y[-1]
        norm_slope = slope / current_price if current_price > 0 else 0
        
        # Coefficient of Determination (R^2)
        # Measures how well the trend line fits the data. 
        # Low R^2 = Choppy/Noisy (Avoid). High R^2 = Clean Trend (Target).
        r_squared = 0
        if denom_x > 0 and denom_y > 0:
            r_squared = (numerator ** 2) / (denom_x * denom_y)
            
        return {
            'slope': norm_slope,
            'r2': r_squared,
            'price': current_price
        }

    def on_price_update(self, prices):
        # 1. Data Ingestion & Maintenance
        active_symbols = set(prices.keys())
        
        # Clean up stale data
        for s in list(self.symbol_data.keys()):
            if s not in active_symbols:
                del self.symbol_data[s]
                
        # Update price history
        for symbol, meta in prices.items():
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = deque(maxlen=self.lookback_window)
            self.symbol_data[symbol].append(meta["priceUsd"])

        # 2. Position Management (Strict Exit Logic)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            
            # Update position stats
            pos['hold_ticks'] += 1
            if current_price > pos['highest_price']:
                pos['highest_price'] = current_price
            
            # Calculate metrics
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown = (current_price - pos['highest_price']) / pos['highest_price']
            
            # --- Exit Rule A: Hard Stop (Anti-STOP_LOSS via early cut) ---
            if pnl_pct < -self.hard_stop_pct:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['HARD_STOP']}
            
            # --- Exit Rule B: Dynamic Trailing Stop ---
            # Activates only after profit threshold is met to lock gains
            if pos['highest_price'] >= entry_price * (1 + self.trailing_trigger):
                if drawdown < -self.trailing_dist:
                    del self.positions[symbol]
                    return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TRAILING_LOCK']}
            
            # --- Exit Rule C: Stagnation Check (Anti-STAGNANT) ---
            # If we bought and it hasn't moved profitably in X ticks, get out.
            # Don't tie up capital in dead assets.
            if pos['hold_ticks'] >= self.stagnant_exit_ticks and pnl_pct < 0.002:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['STAGNANT']}
                
            # --- Exit Rule D: Time Decay (Anti-TIME_DECAY) ---
            if pos['hold_ticks'] >= self.max_hold_ticks:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TIME_LIMIT']}

        # 3. Entry Logic (Momentum & Quality Filter)
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, meta in prices.items():
            if symbol in self.positions: continue
            
            # Liquidity Filter (Execution Safety)
            if meta["liquidity"] < self.min_liquidity: continue
            
            # Price History Check
            history = self.symbol_data.get(symbol)
            if not history or len(history) < 15: continue
            
            # Trend Analysis
            metrics = self._analyze_trend(history)
            if not metrics: continue
            
            # --- FILTERS (Fixing Penalties) ---
            
            # Filter 1: Positive Momentum Only (Anti-MEAN_REVERSION)
            # We strictly buy things already going up. No dip buying.
            if metrics['slope'] <= self.min_slope: continue
            
            # Filter 2: High Trend Quality (Anti-EXPLORE)
            # We only buy smooth trends. Noisy charts hit stop losses too often.
            if metrics['r2'] < self.min_r2_score: continue
            
            # Filter 3: Crash Protection
            # Don't buy if 24h change is catastrophic (falling knife risk despite short term slope)
            if meta["priceChange24h"] < -10.0: continue
            
            # Scoring: Velocity * Consistency
            # We value smooth acceleration.
            score = metrics['slope'] * metrics['r2']
            candidates.append((score, symbol, metrics['price']))
            
        if candidates:
            # Select best asset
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_sym, price = candidates[0]
            
            amount = self.trade_size_usd / price
            
            self.positions[best_sym] = {
                'entry_price': price,
                'amount': amount,
                'highest_price': price,
                'hold_ticks': 0
            }
            
            return {'side': 'BUY', 'symbol': best_sym, 'amount': amount, 'reason': ['MOMENTUM_R2']}
            
        return None