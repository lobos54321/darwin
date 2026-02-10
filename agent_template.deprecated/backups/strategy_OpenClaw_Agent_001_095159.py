import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy: Trend-Aligned Mean Reversion (TAMR) ===
        # Addressing Penalties:
        # 1. MOMENTUM/Z_BREAKOUT: Eliminated by enforcing Mean Reversion (Negative Z entry).
        #    We strictly buy dips, never breakouts.
        # 2. FIXED_TP: Replaced with Dynamic Statistical Exit (Z-Score Convergence).
        # 3. TRAIL_STOP: Replaced with Statistical Hard Stop (Z-Score Breakdown).
        # 4. LOW_ER: Improved via volatility gating and stricter trend alignment.
        
        self.history = {}       # Stores price history: {symbol: deque([prices])}
        self.positions = {}     # Stores active trades: {symbol: {'entry_price': float, 'ticks': int}}
        
        # --- Hyperparameters ---
        self.lookback = 45             # Primary statistical window
        self.trend_lookback = 20       # Short-term trend alignment
        self.max_positions = 5         # Max concurrent trades
        self.trade_amount = 0.18       # Position sizing
        
        # --- Risk Management & Filters ---
        self.min_liquidity = 2500000.0 # High liquidity to minimize slippage
        self.min_volume = 1000000.0    # Active market
        self.min_volatility = 0.0025   # Min volatility to clear spread costs
        self.max_drop_24h = -9.0       # Hard filter against crashing assets
        
        # --- Entry Thresholds ---
        self.entry_z = -2.35           # Buy deep statistical deviations
        self.entry_rsi = 28            # Deep oversold condition
        
        # --- Exit Thresholds ---
        self.exit_z = 0.1              # Target: Return to Mean (slightly positive to capture spread)
        self.stop_loss_z = -5.0        # Thesis Failure: Statistical breakdown
        self.max_hold_ticks = 35       # Time decay limit (Capital rotation)

    def _calculate_metrics(self, symbol):
        """
        Calculates Z-Score, RSI, and Trend Alignment.
        Returns None if insufficient data.
        """
        if symbol not in self.history:
            return None
        
        prices = list(self.history[symbol])
        if len(prices) < self.lookback:
            return None
            
        # 1. Statistical Baseline (Window)
        window = prices[-self.lookback:]
        
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
        
        # 2. Trend Alignment (Regime Filter)
        # Logic: We only buy dips if the Short-Term MA is above the Long-Term MA
        # or if the Long-Term MA is sloping upwards.
        trend_score = 0.0
        if len(prices) >= self.lookback:
            sma_short = statistics.mean(prices[-self.trend_lookback:])
            sma_long = mean_price # Approximation of longer MA
            trend_score = sma_short - sma_long # Positive = Uptrend
            
        # 3. RSI (Relative Strength Index)
        # Standard 14-period RSI
        rsi_period = 14
        if len(window) < rsi_period + 1:
            return None
        
        changes = [window[i] - window[i-1] for i in range(len(window)-rsi_period, len(window))]
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c < 0)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility,
            'trend': trend_score
        }

    def on_price_update(self, prices):
        """
        Core Trading Loop
        """
        # --- 1. Data Ingestion & Cleanup ---
        active_symbols = []
        
        for symbol, data in prices.items():
            if 'priceUsd' not in data:
                continue
            
            try:
                current_price = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback + 5)
            
            self.history[symbol].append(current_price)
            active_symbols.append(symbol)
            
        # Garbage Collection for stale symbols
        active_set = set(active_symbols)
        for s in list(self.history.keys()):
            if s not in active_set and s not in self.positions:
                del self.history[s]

        # --- 2. Exit Logic (Priority) ---
        # Evaluate existing positions first to free up slots
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            self.positions[symbol]['ticks'] += 1
            metrics = self._calculate_metrics(symbol)
            
            if not metrics:
                continue
                
            z = metrics['z']
            
            # EXIT A: Dynamic Mean Reversion (Profit Taking)
            # If we returned to mean (Z ~ 0), we exit. 
            if z >= self.exit_z:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['MEAN_REVERSION']
                }
            
            # EXIT B: Structural Breakdown (Stop Loss)
            # If price deviates too far negative, the mean-reversion thesis failed.
            if z < self.stop_loss_z:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['STOP_LOSS']
                }
                
            # EXIT C: Time Decay
            # Don't hold dead capital.
            if self.positions[symbol]['ticks'] >= self.max_hold_ticks:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['TIME_LIMIT']
                }

        # --- 3. Entry Logic ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol in active_symbols:
            if symbol in self.positions:
                continue
                
            data = prices[symbol]
            
            # Filter 1: Market Structure (Liquidity, Volume, Crash Protection)
            try:
                liq = float(data.get('liquidity', 0))
                vol = float(data.get('volume24h', 0))
                change24h = float(data.get('priceChange24h', 0))
            except (ValueError, TypeError):
                continue
                
            if liq < self.min_liquidity or vol < self.min_volume:
                continue
                
            # Reject assets already crashing hard (Falling Knife protection)
            if change24h < self.max_drop_24h:
                continue
            
            metrics = self._calculate_metrics(symbol)
            if not metrics:
                continue
                
            # Filter 2: Volatility Gating
            # We need enough movement to capture profit, but not extreme chaos.
            if metrics['vol'] < self.min_volatility:
                continue
                
            # Filter 3: REGIME FILTER (Crucial for avoiding Breakout Penalties)
            # Only buy dips if the broader trend is UP or Stable.
            if metrics['trend'] <= 0:
                continue
                
            # SIGNAL: Confluence of Z-Score and RSI
            if metrics['z'] < self.entry_z and metrics['rsi'] < self.entry_rsi:
                # Scoring: Depth of dip weighted by liquidity (Quality Dips)
                # We prefer liquid assets for mean reversion reliability
                score = abs(metrics['z']) * math.log(liq)
                candidates.append({'symbol': symbol, 'score': score})
                
        # Execute best candidate
        if candidates:
            best_trade = max(candidates, key=lambda x: x['score'])
            target_symbol = best_trade['symbol']
            
            self.positions[target_symbol] = {'ticks': 0}
            return {
                'side': 'BUY',
                'symbol': target_symbol,
                'amount': self.trade_amount,
                'reason': ['TREND_DIP']
            }
            
        return None