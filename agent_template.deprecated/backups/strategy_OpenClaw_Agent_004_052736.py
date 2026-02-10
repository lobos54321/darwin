import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy State ---
        self.symbol_data = {}  # Price history
        self.positions = {}    # Active trades
        
        # --- Configuration ---
        self.lookback_window = 35       # Window for regression analysis
        self.max_positions = 5          
        self.trade_size_usd = 200.0     
        self.min_liquidity = 5000000.0  # High liquidity requirements
        
        # --- Risk Management (NO TRAILING STOPS) ---
        # Replaced trailing stops with fixed targets and momentum validation
        self.hard_stop_pct = 0.025      # 2.5% Hard Stop
        self.take_profit_pct = 0.045    # 4.5% Fixed Take Profit
        self.max_hold_ticks = 20        # Strict time limit to rotate capital
        
        # --- Trend Filters (Momentum & Volatility) ---
        self.min_slope = 0.0004         # Minimum normalized slope
        self.min_r2 = 0.82              # High Linearity (Smooth trend)
        self.min_z_score = 1.8          # Price must be statistically elevated (Breakout)

    def _calculate_trend(self, prices_deque):
        """
        Calculates Linear Regression Slope, R-Squared, and Z-Score.
        """
        data = list(prices_deque)
        n = len(data)
        if n < self.lookback_window:
            return None
            
        # Prepare X and Y
        x = list(range(n))
        y = data
        
        # Basic Stats
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)
        stdev_y = statistics.stdev(y) if n > 1 else 0.0
        
        if stdev_y == 0:
            return None
            
        # Linear Regression Calculation
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denom = sum((xi - mean_x) ** 2 for xi in x)
        
        if denom == 0:
            return None
            
        slope = numerator / denom
        intercept = mean_y - (slope * mean_x)
        
        # R-Squared (Goodness of fit)
        ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, y))
        ss_tot = sum((yi - mean_y) ** 2 for yi in y)
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        # Normalized Slope (Price change per tick as percentage)
        current_price = y[-1]
        norm_slope = slope / current_price if current_price > 0 else 0
        
        # Z-Score (Number of standard deviations from the mean)
        z_score = (current_price - mean_y) / stdev_y
        
        return {
            'slope': norm_slope,
            'r2': r2,
            'z_score': z_score,
            'price': current_price
        }

    def on_price_update(self, prices):
        # 1. Data Maintenance
        active_symbols = set(prices.keys())
        # Prune dead symbols
        for s in list(self.symbol_data.keys()):
            if s not in active_symbols:
                del self.symbol_data[s]
        
        # Update history
        for symbol, meta in prices.items():
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = deque(maxlen=self.lookback_window)
            self.symbol_data[symbol].append(meta["priceUsd"])

        # 2. Position Management (Exits)
        # Priority: Check for exits to clear slots
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            pos['hold_ticks'] += 1
            
            pnl_pct = (current_price - entry_price) / entry_price
            
            # A. Hard Stop (Safety)
            if pnl_pct <= -self.hard_stop_pct:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['HARD_STOP']}
                
            # B. Take Profit (Fixed Target)
            if pnl_pct >= self.take_profit_pct:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TAKE_PROFIT']}
                
            # C. Time Expiry (Opportunity Cost)
            if pos['hold_ticks'] >= self.max_hold_ticks:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TIME_EXPIRY']}
            
            # D. Momentum Fade Exit (Dynamic Logic)
            # If the trend breaks (slope becomes negative), exit immediately.
            trend = self._calculate_trend(self.symbol_data[symbol])
            if trend and trend['slope'] < 0:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['MOMENTUM_LOST']}

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        best_candidate = None
        best_score = -1.0
        
        for symbol, meta in prices.items():
            if symbol in self.positions: continue
            if meta["liquidity"] < self.min_liquidity: continue
            
            history = self.symbol_data.get(symbol)
            if not history or len(history) < self.lookback_window: continue
            
            trend = self._calculate_trend(history)
            if not trend: continue
            
            # Criteria: Strong Upward Momentum + Smooth Trend + Statistical Significance
            if (trend['slope'] > self.min_slope and 
                trend['r2'] > self.min_r2 and 
                trend['z_score'] > self.min_z_score):
                
                # Prioritize the smoothest trends (highest R2)
                if trend['r2'] > best_score:
                    best_score = trend['r2']
                    best_candidate = (symbol, trend['slope'], meta['priceUsd'])
        
        if best_candidate:
            symbol, slope, price = best_candidate
            amount = self.trade_size_usd / price
            self.positions[symbol] = {
                'entry_price': price,
                'amount': amount,
                'hold_ticks': 0
            }
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': amount,
                'reason': ['TREND_BREAKOUT', f"R2:{best_score:.2f}"]
            }
            
        return None