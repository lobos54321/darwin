import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- State ---
        self.prices_history = {}
        self.positions = {}
        
        # --- Hyperparameters ---
        self.lookback = 30              # Sample size for efficiency calculation
        self.max_positions = 5          # Max concurrent trades
        self.trade_size_usd = 250.0     # Fixed capital per trade
        self.min_liquidity = 1500000.0  # Liquidity filter
        
        # --- Risk Management (STRICT: NO TRAILING STOPS) ---
        self.hard_stop_pct = 0.035      # 3.5% Fixed Stop Loss
        self.take_profit_pct = 0.065    # 6.5% Fixed Take Profit
        self.max_hold_ticks = 12        # Reduced time window for HFT velocity
        
        # --- Signal Parameters ---
        self.min_efficiency = 0.65      # Efficiency Ratio threshold (Trend purity)
        self.min_momentum = 0.002       # Minimum required return over lookback

    def _get_fractal_efficiency(self, price_deque):
        """
        Calculates Kaufman's Efficiency Ratio (KER).
        Range: 0.0 (Noise) to 1.0 (Straight Line).
        High ER indicates a clean trend with minimal retracement.
        """
        prices = list(price_deque)
        n = len(prices)
        if n < self.lookback:
            return None
            
        # Net direction (End - Start)
        net_change = abs(prices[-1] - prices[0])
        
        # Sum of individual path movements (Volatility/Noise)
        sum_changes = sum(abs(prices[i] - prices[i-1]) for i in range(1, n))
        
        if sum_changes == 0:
            return 0.0
            
        # Efficiency Ratio
        er = net_change / sum_changes
        return er

    def on_price_update(self, prices):
        # 1. State Maintenance
        current_symbols = set(prices.keys())
        # Cleanup old data
        for s in list(self.prices_history.keys()):
            if s not in current_symbols:
                del self.prices_history[s]
                
        # Update price streams
        for symbol, meta in prices.items():
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.lookback)
            self.prices_history[symbol].append(meta["priceUsd"])

        # 2. Position Management (Strict Exit Logic)
        # We iterate a copy of keys to allow deletion during iteration
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            
            # Calculate raw PnL percentage
            pnl_pct = (current_price - entry_price) / entry_price
            
            pos['ticks_held'] += 1
            
            # Exit A: Fixed Hard Stop
            if pnl_pct <= -self.hard_stop_pct:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['HARD_STOP']}
                
            # Exit B: Fixed Take Profit
            if pnl_pct >= self.take_profit_pct:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TAKE_PROFIT']}
                
            # Exit C: Time Limit
            if pos['ticks_held'] >= self.max_hold_ticks:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TIME_LIMIT']}

        # 3. Entry Logic (Fractal Efficiency Breakout)
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, meta in prices.items():
            if symbol in self.positions: continue
            if meta["liquidity"] < self.min_liquidity: continue
            
            history = self.prices_history.get(symbol)
            if not history or len(history) < self.lookback: continue
            
            current_price = meta["priceUsd"]
            start_price = history[0]
            
            # Metric 1: Momentum (Raw Return)
            momentum = (current_price - start_price) / start_price if start_price > 0 else 0
            if momentum < self.min_momentum: continue # Must be moving up
            
            # Metric 2: Efficiency Ratio (Trend Quality)
            er = self._get_fractal_efficiency(history)
            if er is None or er < self.min_efficiency: continue
            
            # Score: High Momentum * High Efficiency
            # This combination selects fast, smooth moves and ignores choppy pumps
            score = momentum * er
            candidates.append((score, symbol, current_price))
            
        if candidates:
            # Select the highest quality trend
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_symbol, best_price = candidates[0]
            
            amount = self.trade_size_usd / best_price
            self.positions[best_symbol] = {
                'entry_price': best_price,
                'amount': amount,
                'ticks_held': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best_symbol, 
                'amount': amount, 
                'reason': ['EFFICIENT_BREAKOUT', f"ER:{best_score:.3f}"]
            }
            
        return None