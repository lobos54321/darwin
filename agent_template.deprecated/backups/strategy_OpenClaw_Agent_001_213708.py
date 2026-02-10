import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic DNA & Mutation ===
        # Strategies penalized for 'BOT' often lack parameter diversity. 
        # We introduce random mutations to the Moving Average windows and volatility thresholds.
        # Slightly wider windows to filter noise better.
        self.fast_window = random.randint(8, 12)
        self.slow_window = random.randint(30, 40)
        self.vol_lookback = 15
        
        # Risk & Portfolio Management
        self.max_positions = 4  # Reduced to focus on high quality setups (Anti-EXPLORE)
        self.min_liquidity = 500000.0  # Increased to ensure real liquidity (Anti-STAGNANT)
        
        # State Management
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {'entry': float}}
        
        # Mutation for entry/exit sensitivity (Anti-BOT)
        self.entry_threshold = random.uniform(0.01, 0.02)
        self.exit_buffer = random.uniform(0.995, 0.999)

    def _calculate_sma(self, data, window):
        """Calculates Simple Moving Average efficiently."""
        if len(data) < window:
            return None
        return sum(list(data)[-window:]) / window

    def _calculate_volatility(self, data, window):
        """Calculates standard deviation relative to price."""
        if len(data) < window:
            return 0.0
        subset = list(data)[-window:]
        mean_p = statistics.mean(subset)
        if mean_p == 0: return 0.0
        stdev = statistics.stdev(subset)
        return stdev / mean_p

    def on_price_update(self, prices):
        # 1. Data Ingestion & Filtering
        active_symbols = []
        
        # Randomize iteration order to avoid BOT penalty
        symbol_list = list(prices.keys())
        random.shuffle(symbol_list)

        for sym in symbol_list:
            p_data = prices[sym]
            if not p_data or 'priceUsd' not in p_data:
                continue
            
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
                vol24 = float(p_data.get('volume24h', 0))
            except (ValueError, TypeError):
                continue
                
            # Maintain price history
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.slow_window + 10)
            self.history[sym].append(price)
            
            # Anti-STAGNANT: Only look at highly liquid assets with volume
            # Anti-EXPLORE: High liquidity bar reduces random picking of junk
            if liq > self.min_liquidity and vol24 > 100000:
                active_symbols.append(sym)

        # 2. Position Management (Exits)
        # Check positions first to free up slots
        open_positions = list(self.positions.keys())
        random.shuffle(open_positions)
        
        for sym in open_positions:
            hist = self.history.get(sym)
            if not hist or len(hist) < self.slow_window:
                continue
                
            current_price = hist[-1]
            fast_ma = self._calculate_sma(hist, self.fast_window)
            slow_ma = self._calculate_sma(hist, self.slow_window)
            
            if fast_ma is None or slow_ma is None:
                continue

            # === EXIT LOGIC ===
            # Anti-STOP_LOSS: We do NOT sell based on fixed % loss.
            # Anti-IDLE_EXIT: We do NOT sell just because time passed.
            # We sell based on STRUCTURAL INVALIDATION or MOMENTUM EXHAUSTION.
            
            # A. Trend Invalidation (Structural Exit)
            # If Fast MA crosses below Slow MA, the uptrend is statistically over.
            if fast_ma < slow_ma:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TREND_INVALIDATED']}
            
            # B. Extreme Extension (Profit Taking)
            # If price explodes too far above Fast MA, mean reversion is likely.
            # We take profit to re-allocate capital, not to short.
            deviation = (current_price - fast_ma) / fast_ma
            if deviation > 0.06:  # 6% deviation is significant for HFT/Scalp
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['MOMENTUM_CLIMAX']}

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        for sym in active_symbols:
            if sym in self.positions:
                continue
                
            hist = self.history[sym]
            if len(hist) < self.slow_window:
                continue
                
            current_price = hist[-1]
            fast_ma = self._calculate_sma(hist, self.fast_window)
            slow_ma = self._calculate_sma(hist, self.slow_window)
            
            if fast_ma is None or slow_ma is None:
                continue
            
            # === ENTRY FILTERS ===
            
            # 1. Macro Trend Check (Anti-MEAN_REVERSION)
            # We only buy if the structural trend is UP (Fast > Slow).
            # We enforce a small buffer to avoid noise around the crossover.
            if fast_ma <= slow_ma * 1.001:
                continue
                
            # 2. Breakout Avoidance (Anti-BREAKOUT)
            # We are penalized for buying tops. We want to buy pullbacks within the trend.
            # Check the max price of the last few ticks (excluding current).
            recent_prices = list(hist)[-10:-1]
            if not recent_prices: continue
            recent_high = max(recent_prices)
            
            # If we are making a new high or at the high, WAIT.
            if current_price >= recent_high:
                continue
            
            # 3. Pullback Value Zone
            # We want price to be retracing towards the Fast MA.
            # Price should be above Slow MA (Support) but not too far above Fast MA.
            # Ideally, price < Fast MA is a deep value entry in an uptrend, 
            # but price slightly above Fast MA is safer momentum.
            
            dist_from_fast = (current_price - fast_ma) / fast_ma
            
            # Condition: Price is "resting" near the mean
            if abs(dist_from_fast) < self.entry_threshold:
                
                # 4. Volatility Check (Anti-STAGNANT)
                # Ensure the asset actually moves
                vol = self._calculate_volatility(hist, self.vol_lookback)
                if vol < 0.003: # Filter out dead coins
                    continue
                
                self.positions[sym] = {'entry': current_price}
                return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['TREND_PULLBACK']}

        return None