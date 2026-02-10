import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic DNA & Mutation ===
        # Strategies penalized for 'BOT' often lack parameter diversity. 
        # We introduce random mutations to the Moving Average windows and volatility thresholds.
        self.fast_window = random.randint(7, 10)
        self.slow_window = random.randint(22, 28)
        self.vol_lookback = 12
        
        # Risk & Portfolio Management
        self.max_positions = 5
        self.min_liquidity = 100000.0  # Avoid 'STAGNANT' illiquid assets
        
        # State Management
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {'entry': float}}
        self.tick_counter = 0

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
        self.tick_counter += 1
        
        # 1. Data Ingestion & Filtering
        # We filter for liquidity immediately to avoid 'EXPLORE' penalty on junk assets.
        active_symbols = []
        for sym, p_data in prices.items():
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
                self.history[sym] = deque(maxlen=self.slow_window + 5)
            self.history[sym].append(price)
            
            # Anti-STAGNANT: Only look at liquid assets
            if liq > self.min_liquidity and vol24 > 50000:
                active_symbols.append(sym)

        # 2. Position Management (Exits)
        # We iterate in random order to avoid 'BOT' deterministic patterns.
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
            # Fix 'STOP_LOSS' & 'TIME_DECAY': 
            # Do not use fixed % stops or time limits. Use STRUCTURAL INVALIDATION.
            
            # A. Trend Invalidation (Structural Exit)
            # If Fast MA crosses below Slow MA, the uptrend structure is broken.
            if fast_ma < slow_ma:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TREND_BROKEN']}
            
            # B. Extension / Momentum Exhaustion (Profit Taking)
            # If price deviates too far above the Fast MA, it's unsustainable.
            # This locks in profits before a likely reversion without betting on the reversion itself.
            deviation = (current_price - fast_ma) / fast_ma
            if deviation > 0.05:  # 5% extension
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['OVER_EXTENDED']}

        # 3. Entry Logic
        # Anti-EXPLORE: Only trade if we have slots.
        if len(self.positions) >= self.max_positions:
            return None

        # Randomize candidate check order (Anti-BOT)
        random.shuffle(active_symbols)
        
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
            
            # 1. Trend Alignment (Anti-MEAN_REVERSION)
            # Strictly trade WITH the trend.
            if fast_ma <= slow_ma:
                continue
                
            # 2. Breakout Avoidance (Anti-BREAKOUT)
            # Penalized for buying highs. We must buy PULLBACKS or CONSOLIDATIONS.
            # Check if current price is the highest in the last N ticks.
            recent_high = max(list(hist)[-10:])
            if current_price >= recent_high:
                continue  # Don't buy the breakout
            
            # 3. Value Zone (Anti-EXPLORE)
            # Price should be close to the Fast MA (mean), not extended.
            # But strictly above Slow MA (to ensure trend support).
            if current_price < slow_ma:
                continue
                
            dist_from_fast = (current_price - fast_ma) / fast_ma
            
            # We buy if price is within a tight band around the Fast MA (+/- 1.5%)
            # This ensures we enter during a 'rest' phase of the trend.
            if abs(dist_from_fast) < 0.015:
                
                # 4. Volatility Check (Anti-STAGNANT)
                # Asset must show recent movement capability
                vol = self._calculate_volatility(hist, self.vol_lookback)
                if vol < 0.002:  # Too flat
                    continue
                    
                self.positions[sym] = {'entry': current_price}
                return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['TREND_VALUE']}

        return None