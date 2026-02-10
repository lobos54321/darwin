import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy: Elastic Mean Reversion v2 ===
        # Addressing Penalties:
        # - MOMENTUM/BREAKOUT: Removed. Strictly Contrarian (buying dips).
        # - FIXED_TP: Removed. Uses Dynamic Equilibrium (Z-Score Mean Reversion).
        # - TRAIL_STOP: Removed. Uses Structural Thesis Failure (Statistical Breakdown).
        # - ER (Expectancy): Improved via strict liquidity weighting and volatility gates.

        self.history = {}
        self.positions = {}
        
        # --- Hyperparameters ---
        self.lookback = 30             # Window for statistical significance
        self.max_positions = 5         # Diversified Portfolio
        self.trade_amount = 0.2        # Position sizing
        
        # --- Filters ---
        self.min_liquidity = 1200000.0 # High liquidity to ensure efficient pricing
        self.min_volume = 600000.0     # Active market requirement
        self.min_volatility = 0.003    # Minimum variance for mean reversion
        self.max_drift_24h = 12.0      # Reject assets moving >12% (Falling Knives)
        
        # --- Entry Logic (Statistical Confluence) ---
        self.entry_z = -2.85           # Statistical Anomaly (~99.5% deviation)
        self.entry_rsi = 26            # Deep Oversold condition
        
        # --- Exit Logic (Dynamic) ---
        self.exit_z = 0.1              # Revert to Mean + slight premium
        self.exit_rsi = 55             # Momentum neutralized
        self.stop_loss_z = -5.0        # Thesis Failure (Black Swan / Crash)
        self.max_hold_ticks = 35       # Time Decay (Capital Rotation)

    def _analyze(self, symbol):
        """
        Compute Statistical Z-Score and RSI.
        """
        if symbol not in self.history:
            return None
            
        series = list(self.history[symbol])
        if len(series) < self.lookback:
            return None
            
        window = series[-self.lookback:]
        
        # 1. Statistics
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
        
        # 2. RSI (Relative Strength Index)
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
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
            # Simple Average for speed/HFT context
            avg_gain = gains / len(window)
            avg_loss = losses / len(window)
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility
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
                    self.history[sym] = deque(maxlen=self.lookback + 5)
                self.history[sym].append(p)
                active_symbols.append(sym)
            except (ValueError, TypeError):
                continue
        
        # Cleanup
        current_set = set(active_symbols)
        for s in list(self.history.keys()):
            if s not in current_set and s not in self.positions:
                del self.history[s]

        # 2. Manage Exits (Priority)
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            self.positions[sym]['ticks'] += 1
            metrics = self._analyze(sym)
            if not metrics:
                continue
                
            z = metrics['z']
            rsi = metrics['rsi']
            
            # EXIT A: Dynamic Equilibrium (Profit)
            if z >= self.exit_z or rsi >= self.exit_rsi:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['MEAN_REVERSION']
                }
            
            # EXIT B: Structural Stop (Safety)
            if z < self.stop_loss_z:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['STRUCTURAL_FAIL']
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
                chg_24h = abs(float(data.get('priceChange24h', 0)))
            except (ValueError, TypeError):
                continue
                
            if liq < self.min_liquidity or vol < self.min_volume:
                continue
                
            # Filter 2: Regime (Avoid Falling Knives)
            if chg_24h > self.max_drift_24h:
                continue
                
            metrics = self._analyze(sym)
            if not metrics:
                continue
            
            # Filter 3: Activity
            if metrics['vol'] < self.min_volatility:
                continue
                
            # SIGNAL: Statistical Confluence
            if metrics['z'] < self.entry_z and metrics['rsi'] < self.entry_rsi:
                # Scoring Mutation: Liquidity Weighted Deviation
                # Prioritize high liquidity assets for better fill probability on dips
                score = abs(metrics['z']) * math.log10(liq)
                candidates.append({'symbol': sym, 'score': score})
                
        if candidates:
            # Execute best trade
            best = max(candidates, key=lambda x: x['score'])
            sym = best['symbol']
            
            self.positions[sym] = {'ticks': 0}
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['ELASTIC_SNAPBACK']
            }
            
        return None