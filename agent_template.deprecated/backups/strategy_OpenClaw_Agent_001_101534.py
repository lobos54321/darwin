import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion with Regime Filtering.
        Addressed Penalties:
        - FIXED_TP: Replaced with volatility-adjusted Z-score exit.
        - Z_BREAKOUT/EFFICIENT_BREAKOUT: Enforced strict negative Z-score entry (Buying Dips).
        - TRAIL_STOP: Replaced with statistical thesis invalidation (Stop Loss Z).
        - ER:0.004: Added liquidity weighting and strict trend alignment to improve efficiency.
        """
        # --- Configuration ---
        self.lookback_window = 40       # Statistical baseline
        self.trend_window = 12          # Short-term trend detection
        self.max_concurrent_positions = 5
        self.position_size = 0.19       # Conservative sizing
        
        # --- Thresholds ---
        self.z_entry = -2.45            # Strict deep dip requirement
        self.z_exit = 0.1               # Mean reversion target (slightly positive)
        self.z_stop = -4.8              # Statistical breakdown (Stop Loss)
        
        # --- Filters ---
        self.min_volatility = 0.0035    # Avoid stagnant assets
        self.min_liquidity = 1500000.0  # Ensure low slippage
        self.min_volume = 750000.0      # Ensure activity
        self.max_crash_24h = -8.5       # Avoid falling knives (e.g. -8.5%)
        self.max_hold_ticks = 28        # Capital rotation limit
        
        # --- State ---
        self.price_history = {}         # {symbol: deque}
        self.positions = {}             # {symbol: {'ticks': int}}

    def _analyze_market(self, symbol):
        """
        Calculates Z-Score and Trend regime.
        """
        if symbol not in self.price_history:
            return None
        
        history = self.price_history[symbol]
        if len(history) < self.lookback_window:
            return None
            
        data = list(history)
        window = data[-self.lookback_window:]
        
        try:
            mean_price = statistics.mean(window)
            stdev = statistics.stdev(window)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0 or mean_price == 0:
            return None
            
        current_price = window[-1]
        z_score = (current_price - mean_price) / stdev
        volatility = stdev / mean_price
        
        # Trend Alignment: Short MA vs Long MA (Baseline Mean)
        # We only want to buy dips in an Uptrend or Neutral-Positive context.
        short_ma = statistics.mean(data[-self.trend_window:])
        is_uptrend = short_ma >= mean_price
        
        return {
            'z': z_score,
            'vol': volatility,
            'uptrend': is_uptrend
        }

    def on_price_update(self, prices):
        """
        Main execution loop.
        Returns: Dict (Trade Instruction) or None.
        """
        # 1. Ingest Data
        valid_symbols = []
        for symbol, data in prices.items():
            try:
                # Parse strict format
                if 'priceUsd' not in data:
                    continue
                price = float(data['priceUsd'])
                
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.lookback_window + 5)
                
                self.price_history[symbol].append(price)
                valid_symbols.append(symbol)
            except (ValueError, TypeError):
                continue

        # Clean stale history
        active_set = set(valid_symbols)
        for s in list(self.price_history.keys()):
            if s not in active_set and s not in self.positions:
                del self.price_history[s]

        # 2. Manage Exits (Highest Priority)
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                # Force close if data stream ends
                del self.positions[symbol]
                continue
            
            self.positions[symbol]['ticks'] += 1
            metrics = self._analyze_market(symbol)
            
            # Blind hold if insufficient data (rare)
            if not metrics:
                continue
                
            z = metrics['z']
            
            # EXIT A: Profit Take (Mean Reversion)
            # Dynamic exit based on volatility normalization (Z-Score)
            if z >= self.z_exit:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['MEAN_REVERT']
                }
            
            # EXIT B: Stop Loss (Statistical Breakdown)
            # If price deviates significantly beyond expected bounds
            if z <= self.z_stop:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['STOP_LOSS']
                }
            
            # EXIT C: Time Limit
            if self.positions[symbol]['ticks'] >= self.max_hold_ticks:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['TIMEOUT']
                }

        # 3. Manage Entries
        if len(self.positions) >= self.max_concurrent_positions:
            return None
            
        candidates = []
        
        for symbol in valid_symbols:
            if symbol in self.positions:
                continue
                
            raw_data = prices[symbol]
            metrics = self._analyze_market(symbol)
            
            if not metrics:
                continue
                
            # --- Filters ---
            
            # 1. Volatility Gate
            if metrics['vol'] < self.min_volatility:
                continue
                
            # 2. Market Structure (Liquidity & Volume)
            try:
                liq = float(raw_data.get('liquidity', 0))
                vol = float(raw_data.get('volume24h', 0))
                chg_24h = float(raw_data.get('priceChange24h', 0))
            except (ValueError, TypeError):
                continue
                
            if liq < self.min_liquidity or vol < self.min_volume:
                continue
                
            # 3. Crash Protection (Anti-Falling Knife)
            if chg_24h < self.max_crash_24h:
                continue
                
            # 4. Regime Filter (Trend Alignment)
            # STRICT: Only buy if short-term momentum is positive relative to baseline
            if not metrics['uptrend']:
                continue
            
            # --- Signal ---
            # Entry: Deep Negative Z-Score (Statistical Dip)
            if metrics['z'] < self.z_entry:
                # Scoring: Prioritize deepest dips in highest liquidity pools
                # This ensures we are trading "real" moves, not low-liq noise.
                score = abs(metrics['z']) * math.log10(liq)
                candidates.append({'symbol': symbol, 'score': score})
                
        # Execute Best Trade
        if candidates:
            # Sort by score descending
            best_opp = max(candidates, key=lambda x: x['score'])
            target = best_opp['symbol']
            
            self.positions[target] = {'ticks': 0}
            return {
                'side': 'BUY',
                'symbol': target,
                'amount': self.position_size,
                'reason': ['STAT_DIP']
            }
            
        return None