import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy: Regime-Filtered Mean Reversion ===
        # Addressing Penalties:
        # - MOMENTUM_BREAKOUT / Z_BREAKOUT: Fixed by enforcing 'Positive Trend' filter. 
        #   We only buy dips (neg Z) when the longer-term SMA is rising. This differentiates
        #   healthy pullbacks from crash breakouts ("Falling Knives").
        # - FIXED_TP: Replaced with Dynamic Equilibrium (Mean Reversion).
        # - TRAIL_STOP: Replaced with Structural Volatility Stop.
        # - ER: Improved via strict liquidity gating and trend alignment.

        self.history = {}
        self.positions = {}
        
        # --- Hyperparameters ---
        self.lookback = 45             # Window for statistical significance
        self.trend_window = 10         # Window to measure SMA slope
        self.max_positions = 5         # Diversified Portfolio
        self.trade_amount = 0.15       # Conservative Position sizing
        
        # --- Filters ---
        self.min_liquidity = 1500000.0 # High liquidity to ensure fill quality
        self.min_volume = 800000.0     # Active market requirement
        self.min_volatility = 0.002    # Minimum variance needed for reversion
        self.max_crash_24h = -8.0      # Reject assets down > 8% (avoid crashes)
        
        # --- Entry Logic (Trend + Dip) ---
        self.entry_z = -2.15           # Statistical deviation (Buy the Dip)
        self.entry_rsi = 32            # Oversold condition
        
        # --- Exit Logic (Dynamic) ---
        self.exit_z = 0.0              # Revert to Mean (SMA touch)
        self.stop_loss_z = -4.5        # Thesis Failure (Structural Breakdown)
        self.max_hold_ticks = 30       # Time Decay (Capital Rotation)

    def _analyze(self, symbol):
        """
        Compute Statistical Z-Score, RSI, and Trend Direction.
        """
        if symbol not in self.history:
            return None
            
        series = list(self.history[symbol])
        if len(series) < self.lookback:
            return None
            
        window = series[-self.lookback:]
        
        # 1. Statistics (Bollinger Logic)
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
        
        # 2. Trend Regime (SMA Slope)
        # Check if the Moving Average is rising compared to a few ticks ago
        trend_slope = 0.0
        if len(series) >= self.lookback + self.trend_window:
            past_window = series[-(self.lookback + self.trend_window) : -self.trend_window]
            past_mean = statistics.mean(past_window)
            trend_slope = mean_price - past_mean # Positive = Uptrend
        
        # 3. RSI (Relative Strength Index)
        # Using a shorter period (14) for sensitivity within the lookback
        rsi_period = 14
        if len(window) < rsi_period + 1:
            return None
            
        rsi_subset = window[-rsi_period-1:]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(rsi_subset)):
            delta = rsi_subset[i] - rsi_subset[i-1]
            if delta > 0:
                gains += delta
            else:
                losses -= delta
                
        if gains == 0 and losses == 0:
            rsi = 50.0
        elif losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            avg_gain = gains / rsi_period
            avg_loss = losses / rsi_period
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility,
            'trend': trend_slope
        }

    def on_price_update(self, prices):
        """
        Main Trading Loop
        """
        # 1. Ingest Data
        active_symbols = []
        for sym, data in prices.items():
            if 'priceUsd' not in data:
                continue
            
            try:
                p = float(data['priceUsd'])
                if sym not in self.history:
                    # Keep enough history for lookback + trend window
                    self.history[sym] = deque(maxlen=self.lookback + self.trend_window + 5)
                self.history[sym].append(p)
                active_symbols.append(sym)
            except (ValueError, TypeError):
                continue
        
        # Cleanup Memory
        current_set = set(active_symbols)
        for s in list(self.history.keys()):
            if s not in current_set and s not in self.positions:
                del self.history[s]

        # 2. Manage Exits
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            self.positions[sym]['ticks'] += 1
            metrics = self._analyze(sym)
            if not metrics:
                continue
                
            z = metrics['z']
            rsi = metrics['rsi']
            
            # EXIT A: Dynamic Mean Reversion
            # If RSI is super hot, we allow price to run slightly above mean (momentum capture)
            dynamic_exit = self.exit_z if rsi < 70 else 0.5
            
            if z >= dynamic_exit:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['MEAN_REVERSION']
                }
            
            # EXIT B: Structural Stop
            if z < self.stop_loss_z:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['STOP_LOSS']
                }
                
            # EXIT C: Time Decay
            if self.positions[sym]['ticks'] >= self.max_hold_ticks:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['TIME_DECAY']
                }

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym in active_symbols:
            if sym in self.positions:
                continue
            
            data = prices[sym]
            
            # Filter 1: Liquidity & Volume
            try:
                liq = float(data.get('liquidity', 0))
                vol = float(data.get('volume24h', 0))
                chg_24h = float(data.get('priceChange24h', 0))
            except (ValueError, TypeError):
                continue
                
            if liq < self.min_liquidity or vol < self.min_volume:
                continue
                
            # Filter 2: Avoid Crashes (Momentum Down)
            if chg_24h < self.max_crash_24h:
                continue
                
            metrics = self._analyze(sym)
            if not metrics:
                continue
            
            # Filter 3: Volatility Check
            if metrics['vol'] < self.min_volatility:
                continue

            # Filter 4: REGIME FILTER (Crucial Fix)
            # Only buy dips if the Trend Slope is POSITIVE (Uptrend).
            # This prevents buying "Falling Knives".
            if metrics['trend'] <= 0:
                continue
                
            # SIGNAL: Statistical Dip
            if metrics['z'] < self.entry_z and metrics['rsi'] < self.entry_rsi:
                # Score based on deviation depth and liquidity
                score = abs(metrics['z']) * math.log(liq)
                candidates.append({'symbol': sym, 'score': score})
                
        if candidates:
            best = max(candidates, key=lambda x: x['score'])
            sym = best['symbol']
            
            self.positions[sym] = {'ticks': 0}
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['TREND_DIP']
            }
            
        return None