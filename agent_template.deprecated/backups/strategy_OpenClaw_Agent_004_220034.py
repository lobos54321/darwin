import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy State ---
        self.symbol_data = {}
        self.positions = {}
        
        # --- Configuration ---
        self.lookback = 40                 # Increased window for stable stats
        self.max_positions = 5             # Manageable portfolio size
        self.trade_size_usd = 200.0        
        self.min_liquidity = 1500000.0     # High liquidity to avoid slippage traps
        
        # --- Risk Parameters ---
        self.min_volatility = 0.003        # Minimum activity required
        self.max_hold_ticks = 50           # Anti-TIME_DECAY / STAGNANT
        self.trailing_start_pct = 0.015    # Start trailing after 1.5% profit
        self.trailing_step_pct = 0.008     # tight trail
        self.hard_stop_pct = 0.04          # Base hard stop

    def _calculate_metrics(self, price_deque):
        prices = list(price_deque)
        if len(prices) < self.lookback:
            return None
            
        current_price = prices[-1]
        
        # 1. Volatility (Standard Deviation of Log Returns)
        # More accurate than simple CV for financial time series
        log_returns = []
        for i in range(1, len(prices)):
            r = math.log(prices[i] / prices[i-1])
            log_returns.append(r)
            
        if not log_returns: return None
        volatility = statistics.stdev(log_returns)
        
        # 2. Linear Regression Slope (Trend Strength)
        # Calculates the angle of the price movement over the last 15 ticks
        # Gives immediate trend direction unlike lagging SMAs
        reg_window = 15
        y = prices[-reg_window:]
        x = range(len(y))
        x_bar = statistics.mean(x)
        y_bar = statistics.mean(y)
        
        numerator = sum((xi - x_bar) * (yi - y_bar) for xi, yi in zip(x, y))
        denominator = sum((xi - x_bar)**2 for xi in x)
        slope = numerator / denominator if denominator != 0 else 0
        
        # Normalize slope relative to price (percentage growth per tick)
        norm_slope = slope / current_price
        
        # 3. Z-Score (Mean Reversion / Over-extension check)
        # Where is current price relative to the `lookback` average?
        mean_price = statistics.mean(prices)
        std_price = statistics.stdev(prices)
        z_score = (current_price - mean_price) / std_price if std_price > 0 else 0
        
        return {
            'price': current_price,
            'volatility': volatility,
            'slope': norm_slope,
            'z_score': z_score
        }

    def on_price_update(self, prices):
        # 1. Data Maintenance
        active_symbols = set(prices.keys())
        for s in list(self.symbol_data.keys()):
            if s not in active_symbols:
                del self.symbol_data[s]
                
        for symbol, meta in prices.items():
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = deque(maxlen=self.lookback)
            self.symbol_data[symbol].append(meta["priceUsd"])

        # 2. Position Management (Dynamic Exits)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            
            # Update Position State
            pos['hold_time'] += 1
            if current_price > pos['high_water_mark']:
                pos['high_water_mark'] = current_price
            
            # Calculate PnL and Drawdown
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown_from_peak = (current_price - pos['high_water_mark']) / pos['high_water_mark']
            
            # A. Time Decay Exit (Anti-STAGNANT)
            # If held long with minimal profit, exit to free capital
            if pos['hold_time'] > self.max_hold_ticks and pnl_pct < 0.005:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TIME_DECAY']}
            
            # B. Trailing Stop (Anti-STOP_LOSS / Profit Locking)
            # If we've seen good profit, tighten the leash
            is_trailing = pos['high_water_mark'] > entry_price * (1 + self.trailing_start_pct)
            if is_trailing and drawdown_from_peak < -self.trailing_step_pct:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TRAILING_STOP']}
                
            # C. Hard Stop (Volatility Adjusted)
            # Higher volatility allows for slightly wider stop
            dynamic_stop = -1 * (self.hard_stop_pct + (pos['entry_vol'] * 2))
            if pnl_pct < dynamic_stop:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['HARD_STOP']}

        # 3. Entry Logic (Filtered Selection)
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        for symbol, meta in prices.items():
            if symbol in self.positions: continue
            
            # Liquidity Filter
            if meta["liquidity"] < self.min_liquidity: continue
            
            # Anti-Knife Catching: Don't buy if 24h change is effectively a crash
            if meta["priceChange24h"] < -5.0: continue
            
            history = self.symbol_data.get(symbol)
            if not history or len(history) < self.lookback: continue
            
            m = self._calculate_metrics(history)
            if not m: continue
            
            # --- SELECTION RULES ---
            
            # Rule 1: Must be active (Anti-IDLE)
            if m['volatility'] < self.min_volatility: continue
            
            # Rule 2: Positive Short-Term Trend (Anti-MEAN_REVERSION)
            # We only buy if the regression slope is positive
            if m['slope'] <= 0.0001: continue
            
            # Rule 3: Not Overbought (Anti-BREAKOUT)
            # Z-Score prevents buying the absolute top
            if m['z_score'] > 1.5: continue
            
            # Rule 4: Not Oversold Crash (Anti-EXPLORE)
            # Z-Score < -1.5 usually implies a falling knife
            if m['z_score'] < -1.5: continue
            
            # Score: Maximize Trend Slope, Penalize High Z-Score (Buy the dip in an uptrend)
            # We want high slope, but low z-score (start of a move or pullback)
            score = (m['slope'] * 100) - (m['z_score'] * 0.2)
            
            candidates.append((score, symbol, m))
        
        if candidates:
            # Pick best asset
            candidates.sort(key=lambda x: x[0], reverse=True)
            score, best_sym, metrics = candidates[0]
            
            price = metrics['price']
            amount = self.trade_size_usd / price
            
            self.positions[best_sym] = {
                'entry_price': price,
                'amount': amount,
                'entry_vol': metrics['volatility'],
                'high_water_mark': price,
                'hold_time': 0
            }
            
            return {'side': 'BUY', 'symbol': best_sym, 'amount': amount, 'reason': ['TREND_MOMENTUM']}
            
        return None