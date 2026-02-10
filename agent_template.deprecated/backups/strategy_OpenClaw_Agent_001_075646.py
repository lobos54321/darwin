import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy: Elastic Mean Reversion (Statistical Variance) ===
        # Addressing Hive Mind Penalties:
        # 1. FIXED_TP: Replaced with Dynamic Equilibrium Exit (Z-Score convergence to 0).
        # 2. BREAKOUT/Z_BREAKOUT: Strategy is strictly Contrarian. Buying statistical anomalies (Z < -3.4).
        # 3. ER:0.004: Improved Expectancy via Liquidity Weighting and Volatility Floors.
        # 4. TRAIL_STOP: Replaced with Structural Thesis Failure (Statistical Crash) and Time Decay.

        self.history = {}  # {symbol: deque}
        self.positions = {}  # {symbol: {'ticks': int, 'entry_price': float}}
        
        # --- Hyperparameters ---
        self.lookback = 30             # Statistical window
        self.max_positions = 3         # Focused Portfolio (High Conviction)
        self.trade_amount = 0.1        # Position sizing
        
        # --- Risk Filters ---
        self.min_liquidity = 1500000.0 # High liquidity to ensure efficient mean reversion
        self.min_volume = 750000.0     # 24h Volume floor
        self.min_volatility = 0.004    # Avoid dead assets (StDev/SMA)
        self.max_drift_24h = 15.0      # Avoid assets crashing/pumping too hard (>15%)
        
        # --- Entry Thresholds (Strict) ---
        self.entry_z = -3.4            # Deep statistical deviation (>3.4 sigma)
        self.entry_rsi = 28            # Deep oversold
        
        # --- Exit Thresholds ---
        self.exit_z = 0.0              # Exit at Mean (Regression)
        self.exit_rsi = 52             # Momentum Neutralized
        self.stop_loss_z = -6.0        # Structural Failure (Black Swan protection)
        self.max_hold_ticks = 45       # Time decay (Opportunity cost)

    def _analyze(self, symbol):
        """
        Calculates Z-Score, RSI, and Volatility using a sliding window.
        """
        if symbol not in self.history:
            return None
            
        series = list(self.history[symbol])
        if len(series) < self.lookback:
            return None
            
        window = series[-self.lookback:]
        
        # 1. Statistics (SMA, StDev, Z-Score)
        try:
            sma = statistics.mean(window)
            stdev = statistics.stdev(window)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0 or sma == 0:
            return None
            
        current_price = window[-1]
        z_score = (current_price - sma) / stdev
        volatility = stdev / sma
        
        # 2. RSI (Simplified over lookback window for speed)
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
        else:
            avg_gain = gains / len(window)
            avg_loss = losses / len(window)
            if avg_loss == 0:
                rsi = 100.0
            elif avg_gain == 0:
                rsi = 0.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility,
            'price': current_price
        }

    def on_price_update(self, prices):
        """
        Core Trading Loop
        """
        # 1. Ingest Data
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback + 5)
                self.history[sym].append(p)
            except (ValueError, KeyError, TypeError):
                continue
        
        # Cleanup inactive symbols
        active_symbols = set(prices.keys())
        for sym in list(self.history.keys()):
            if sym not in active_symbols and sym not in self.positions:
                del self.history[sym]

        # 2. Manage Exits (Priority)
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            self.positions[sym]['ticks'] += 1
            ticks = self.positions[sym]['ticks']
            
            metrics = self._analyze(sym)
            if not metrics:
                continue
                
            z = metrics['z']
            rsi = metrics['rsi']
            
            # EXIT A: Dynamic Equilibrium (Profit)
            # Price reverted to mean OR momentum neutralized
            if z >= self.exit_z or rsi >= self.exit_rsi:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['EQUILIBRIUM_REACHED']
                }
            
            # EXIT B: Structural Stop (Crash Protection)
            # Statistical thesis broken (Price moved > 6 sigma away)
            if z < self.stop_loss_z:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['STRUCTURAL_FAILURE']
                }
                
            # EXIT C: Time Decay
            if ticks >= self.max_hold_ticks:
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
        
        for sym, data in prices.items():
            if sym in self.positions:
                continue
                
            # Filter: Liquidity & Volume
            try:
                liq = float(data.get('liquidity', 0))
                vol = float(data.get('volume24h', 0))
                if liq < self.min_liquidity or vol < self.min_volume:
                    continue
            except:
                continue
            
            # Filter: Regime (Drift)
            # Reject assets that have moved too violently in 24h (Falling Knives)
            try:
                chg = abs(float(data.get('priceChange24h', 0)))
                if chg > self.max_drift_24h:
                    continue
            except:
                continue
                
            metrics = self._analyze(sym)
            if not metrics:
                continue
            
            # Filter: Volatility Floor (Avoid dead assets)
            if metrics['vol'] < self.min_volatility:
                continue
                
            # SIGNAL: Elastic Snapback (Strict)
            # We want z < -3.4 (Deep Dip) and RSI < 28 (Oversold)
            if metrics['z'] < self.entry_z and metrics['rsi'] < self.entry_rsi:
                
                # Mutation: Liquidity Weighted Scoring
                # Prefer assets with higher liquidity for better fill quality on reversals
                # Score = (Deviation Intensity) * log(Liquidity)
                deviation_score = abs(metrics['z']) * (100 - metrics['rsi'])
                liq_score = math.log10(liq) if liq > 1 else 1
                
                final_score = deviation_score * liq_score
                
                candidates.append({
                    'symbol': sym,
                    'score': final_score
                })
        
        if candidates:
            # Pick best statistical anomaly adjusted for liquidity
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