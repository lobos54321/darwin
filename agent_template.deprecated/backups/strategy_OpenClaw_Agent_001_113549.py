import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Dynamic Volatility-Gated Mean Reversion.
        
        Fixes for Hive Mind Penalties:
        1. EFFICIENT_BREAKOUT / Z_BREAKOUT: 
           - Implemented a 'Volatility Gate'. We only enter mean reversion trades if 
             short-term volatility is NOT significantly expanding relative to long-term volatility.
           - This prevents buying into an accelerating trend (catching a falling knife).
        2. ER:0.004 (Low Edge):
           - Implemented 'Dynamic Z-Scoring'. The entry threshold adapts to market conditions.
             Higher volatility requires a deeper dip (lower Z-score) to trigger a buy.
           - Stricter liquidity and crash filters.
        3. FIXED_TP / TRAIL_STOP:
           - Removed. Exits are strictly statistical (Z-Score reversion) or time-based.
        """
        self.lookback_long = 60             # Long window for stable baseline
        self.lookback_short = 10            # Short window for detecting vol expansion
        
        self.max_positions = 5
        self.wallet_alloc = 0.20            # 20% per position
        
        # Risk & Filters
        self.min_liquidity = 5000000.0      # Min $5M liquidity
        self.min_price_change = -12.0       # Filter out assets crashing > 12% in 24h
        
        # Volatility Gating (Anti-Breakout)
        self.max_vol_ratio = 1.6            # Max allowed (Short_Std / Long_Std). Above this = Trend Mode.
        
        # Dynamic Entry Logic
        self.base_z_trigger = -2.3          # Base deviation for entry
        self.vol_z_penalty = 1.2            # Extra Z-depth required per unit of excess volatility
        self.entry_rsi = 30                 # Stricter RSI limit
        
        # Exit Logic
        self.exit_z_target = 0.1            # Exit slightly above mean (pay for spread)
        self.stop_loss_z = -5.2             # Structural break stop (Thesis Invalidated)
        self.max_hold_ticks = 45            # Time based rotation
        
        # State Management
        self.prices_history = {}            # {symbol: deque}
        self.positions = {}                 # {symbol: {tick: int, price: float}}
        self.cooldowns = {}                 # {symbol: int}
        self.tick_counter = 0

    def _get_metrics(self, symbol):
        """Calculates Z-Score, Volatility Ratio, and RSI."""
        history = self.prices_history.get(symbol)
        if not history or len(history) < self.lookback_long:
            return None
            
        data = list(history)
        current_price = data[-1]
        
        # 1. Long-Term Statistics (Baseline)
        try:
            mean_long = statistics.mean(data)
            stdev_long = statistics.stdev(data)
        except statistics.StatisticsError:
            return None
            
        if stdev_long == 0:
            return None
            
        z_score = (current_price - mean_long) / stdev_long
        
        # 2. Short-Term Volatility (Trend Detection)
        recent_data = data[-self.lookback_short:]
        try:
            stdev_short = statistics.stdev(recent_data)
        except statistics.StatisticsError:
            stdev_short = stdev_long
            
        # Ratio > 1.0 implies volatility is heating up (potential breakout/crash)
        vol_ratio = stdev_short / stdev_long
        
        # 3. RSI (14)
        period = 14
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        if len(deltas) < period:
            rsi = 50
        else:
            recent_deltas = deltas[-period:]
            gains = sum(d for d in recent_deltas if d > 0) / period
            losses = sum(abs(d) for d in recent_deltas if d < 0) / period
            
            if losses == 0:
                rsi = 100
            else:
                rsi = 100 - (100 / (1 + (gains / losses)))
        
        return {
            'z': z_score,
            'vol_ratio': vol_ratio,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # --- 1. Data Ingestion ---
        active_symbols = []
        
        # Prune dead history
        current_market_keys = set(prices.keys())
        for s in list(self.prices_history.keys()):
            if s not in current_market_keys:
                del self.prices_history[s]

        for symbol, data in prices.items():
            if 'priceUsd' not in data:
                continue
            
            try:
                price = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            active_symbols.append(symbol)
            
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.lookback_long)
            self.prices_history[symbol].append(price)
            
            # Tick down cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # --- 2. Exit Logic (Priority) ---
        for symbol in list(self.positions.keys()):
            # Emergency clean up if data stops
            if symbol not in prices:
                if self.tick_counter - self.positions[symbol]['tick'] > self.max_hold_ticks:
                    del self.positions[symbol]
                continue

            metrics = self._get_metrics(symbol)
            if not metrics:
                continue
                
            pos_info = self.positions[symbol]
            hold_duration = self.tick_counter - pos_info['tick']
            
            # A. Statistical Mean Reversion (Target)
            # We exit when price returns to slightly above mean
            if metrics['z'] >= self.exit_z_target:
                del self.positions[symbol]
                self.cooldowns[symbol] = 10
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['MEAN_REVERTED']
                }
            
            # B. Statistical Hard Stop
            # If price deviates beyond -5.2 sigma, the statistical model is broken
            if metrics['z'] < self.stop_loss_z:
                del self.positions[symbol]
                self.cooldowns[symbol] = 50 # Long cooldown on loss
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['STATISTICAL_STOP']
                }
                
            # C. Time Rotation
            if hold_duration >= self.max_hold_ticks:
                del self.positions[symbol]
                self.cooldowns[symbol] = 5
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': ['TIME_LIMIT']
                }

        # --- 3. Entry Logic ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol in active_symbols:
            if symbol in self.positions or symbol in self.cooldowns:
                continue
                
            price_data = prices[symbol]
            
            # Filters
            try:
                liq = float(price_data.get('liquidity', 0))
                chg_24h = float(price_data.get('priceChange24h', 0))
            except:
                continue
                
            if liq < self.min_liquidity:
                continue
            if chg_24h < self.min_price_change:
                continue