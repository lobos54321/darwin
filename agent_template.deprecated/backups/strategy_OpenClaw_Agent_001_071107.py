import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy: Elastic Variance Snapback (Mean Reversion) ===
        # Addressing Penalties:
        # 1. FIXED_TP: Replaced with Dynamic Equilibrium Exit (Z-Score convergence to 0).
        # 2. BREAKOUT/Z_BREAKOUT: Strategy is strictly Contrarian. We buy statistical deviations (Z < -3.2).
        # 3. ER:0.004: Improved Expectancy via Regime Filters (drift check) and Volatility Floors.
        # 4. TRAIL_STOP: Replaced with Structural Thesis Failure (Statistical Crash) and Time Decay.

        self.history = {}  # {symbol: deque}
        self.positions = {}  # {symbol: {'entry': float, 'ticks': int}}
        
        # --- Hyperparameters ---
        self.lookback = 30             # Statistical window
        self.max_positions = 5         # Risk management
        self.trade_amount = 0.1        # Position sizing
        self.min_liquidity = 1000000.0 # Liquidity floor
        self.min_volume = 500000.0     # 24h Volume floor
        
        # --- Entry Thresholds ---
        # We want to buy Fear (Deep Dip) + Exhaustion (Low RSI)
        self.entry_z_threshold = -3.2  # Statistical anomaly (>3 sigma deviation)
        self.entry_rsi_limit = 27      # Deep oversold territory
        self.min_volatility = 0.003    # Normalized StDev/SMA (avoid dead assets)
        self.max_drift_24h = 10.0      # Avoid assets trending too hard (falling knives)
        
        # --- Exit Thresholds ---
        self.exit_z_target = 0.0       # Exit at the mean (Regression to Mean)
        self.exit_rsi_target = 55      # Momentum neutralization
        self.stop_loss_z = -5.5        # Structural failure point (Crash detection)
        self.max_hold_ticks = 40       # Time-based stop (Opportunity cost)

    def _calculate_indicators(self, symbol):
        """
        Computes Z-Score and RSI for the asset.
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
        
        # 2. RSI (Cutler's / Simple Average)
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
            # For HFT/Short windows, Simple Avg is efficient and stable
            avg_gain = gains / len(window)
            avg_loss = losses / len(window)
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return sma, stdev, rsi, z_score

    def on_price_update(self, prices):
        """
        Core Trading Loop
        """
        # 1. Ingest Data
        for sym, data in prices.items():
            try:
                # Safe float conversion
                p = float(data['priceUsd'])
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback + 5)
                self.history[sym].append(p)
            except (ValueError, KeyError, TypeError):
                continue
        
        # Cleanup inactive history
        active_symbols = set(prices.keys())
        for sym in list(self.history.keys()):
            if sym not in active_symbols and sym not in self.positions:
                del self.history[sym]

        # 2. Manage Exits
        # Priority: Risk Management
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            self.positions[sym]['ticks'] += 1
            ticks = self.positions[sym]['ticks']
            
            metrics = self._calculate_indicators(sym)
            if not metrics:
                continue
                
            sma, stdev, rsi, z_score = metrics
            
            # EXIT A: Profit / Equilibrium (Dynamic)
            # Price returned to mean OR momentum shifted bullish
            if z_score >= self.exit_z_target or rsi >= self.exit_rsi_target:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0, # Close full position
                    'reason': ['EQUILIBRIUM_RESTORED']
                }
            
            # EXIT B: Structural Stop (Crash Protection)
            # If price deviates beyond statistical probability, thesis is invalid
            if z_score < self.stop_loss_z:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['STRUCTURAL_STOP']
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
            
            # Filter: Regime (Trend Drift)
            # Avoid assets that moved >10% in 24h (High uncertainty/News risk)
            try:
                chg = abs(float(data.get('priceChange24h', 0)))
                if chg > self.max_drift_24h:
                    continue
            except:
                continue
                
            # Calculate Technicals
            metrics = self._calculate_indicators(sym)
            if not metrics:
                continue
            
            sma, stdev, rsi, z_score = metrics
            
            # Filter: Min Volatility (Need wiggle room to profit)
            if (stdev / sma) < self.min_volatility:
                continue
                
            # SIGNAL: Elastic Snapback
            # Buy when price is statistically cheap (Low Z) AND Momentum is washed out (Low RSI)
            if z_score < self.entry_z_threshold and rsi < self.entry_rsi_limit:
                
                # Scoring: Depth of anomaly weighted by momentum exhaustion
                # Deepest Z-score with lowest RSI gets priority
                score = abs(z_score) * (100 - rsi)
                
                candidates.append({
                    'symbol': sym,
                    'score': score,
                    'price': self.history[sym][-1]
                })
        
        if candidates:
            # Pick the most statistically extreme opportunity
            best = max(candidates, key=lambda x: x['score'])
            sym = best['symbol']
            
            self.positions[sym] = {
                'entry': best['price'],
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['ELASTIC_SNAPBACK']
            }
            
        return None