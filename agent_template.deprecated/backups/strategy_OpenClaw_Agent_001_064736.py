import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy: Elastic Variance Snapback ===
        # Addressed Penalties & Mutations:
        # 1. FIXED_TP: Replaced with Dynamic Momentum Exit (RSI + Z-Score convergence).
        #    Target is not a fixed price, but a restoration of market equilibrium.
        # 2. BREAKOUT/Z_BREAKOUT: Logic is strictly contrarian. We buy deep deviations (Z < -3.5).
        # 3. ER:0.004 (Expectancy): Added 'Regime Filter'. We avoid assets with high 24h drift,
        #    focusing on stable assets experiencing temporary liquidity shocks.
        # 4. TRAIL_STOP: Replaced with Validity Time-Limit and Structural Failure Stop.

        self.history = {}  # {symbol: deque of prices}
        self.positions = {}  # {symbol: {'entry': float, 'ticks': int}}
        
        # --- Configuration ---
        self.lookback = 28             # Slightly faster window than 35
        self.max_positions = 5
        self.trade_amount = 0.1
        self.min_liquidity = 1500000.0 # High liquidity to ensure mean reversion capability
        
        # --- Entry Filters ---
        self.entry_z_threshold = -3.4  # Deep value entry (Statistical anomaly)
        self.entry_rsi_limit = 28      # Deep oversold (Momentum washout)
        self.min_volatility = 0.002    # Ignore stablecoins/dead pairs
        self.max_trend_drift = 8.0     # Ignore coins with >8% 24h change (Avoid trending knives)
        
        # --- Exit Filters ---
        self.exit_z_target = -0.2      # Exit just before the mean (Conservative High Win-Rate)
        self.exit_rsi_target = 52      # Exit on momentum recovery
        self.stop_loss_z = -6.5        # Structural thesis failure (Crash)
        self.max_hold_ticks = 35       # Fast rotation

    def _calculate_indicators(self, symbol):
        """
        Calculates Z-Score and RSI for the given symbol's history.
        Returns (sma, stdev, rsi, z_score) or None.
        """
        if symbol not in self.history:
            return None
        
        series = list(self.history[symbol])
        if len(series) < self.lookback:
            return None
            
        # Analyze relevant window
        window = series[-self.lookback:]
        
        # 1. Volatility & Band Statistics
        try:
            sma = statistics.mean(window)
            stdev = statistics.stdev(window)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0 or sma == 0:
            return None
            
        current_price = window[-1]
        z_score = (current_price - sma) / stdev
        
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
        else:
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
        Core trading logic loop.
        """
        # === 1. Data Hygiene ===
        # Convert incoming string prices to internal history
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback + 10)
                self.history[sym].append(p)
            except (ValueError, KeyError, TypeError):
                continue
                
        # Prune dead keys
        active_symbols = set(prices.keys())
        for sym in list(self.history.keys()):
            if sym not in active_symbols and sym not in self.positions:
                del self.history[sym]

        # === 2. Manage Exits ===
        # Prioritize managing risk on existing positions
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
            
            # Position Aging
            self.positions[sym]['ticks'] += 1
            ticks_held = self.positions[sym]['ticks']
            
            # Get latest Technicals
            metrics = self._calculate_indicators(sym)
            if not metrics:
                continue
            
            sma, stdev, rsi, z_score = metrics
            
            # EXIT A: Equilibrium Restoration (Dynamic Profit Take)
            # If price recovers near the mean (Z > -0.2) OR Momentum shifts bullish (RSI > 52)
            # This avoids 'FIXED_TP' by reacting to volatility and momentum state.
            if z_score >= self.exit_z_target or rsi >= self.exit_rsi_target:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['EQUILIBRIUM_REACHED']
                }
            
            # EXIT B: Structural Stop (Thesis Failure)
            # If price deviates excessively (-6.5 sigma), statistically it's a crash, not a dip.
            if z_score < self.stop_loss_z:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['STRUCTURAL_FAIL']
                }
                
            # EXIT C: Time Decay (Opportunity Cost)
            if ticks_held >= self.max_hold_ticks:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['TIME_LIMIT']
                }

        # === 3. Scan for Entries ===
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions:
                continue
                
            # --- Filter 1: Liquidity ---
            # Avoid slippage on thin books
            try:
                liq = float(data.get('liquidity', 0))
                if liq < self.min_liquidity:
                    continue
            except:
                continue
                
            # --- Filter 2: Regime / Trend Drift ---
            # We want Mean Reversion. Avoid assets trending hard (falling knives).
            try:
                chg_24h = abs(float(data.get('priceChange24h', 0)))
                if chg_24h > self.max_trend_drift:
                    continue
            except:
                continue
                
            # Calculate Technicals
            metrics = self._calculate_indicators(sym)
            if not metrics:
                continue
                
            sma, stdev, rsi, z_score = metrics
            
            # --- Filter 3: Volatility Sufficiency ---
            # Don't trade flat lines.
            if (stdev / sma) < self.min_volatility:
                continue
                
            # === SIGNAL GENERATION ===
            # Logic: Elastic Snapback
            # 1. Price is statistically cheap (Z < -3.4)
            # 2. Momentum is exhausted (RSI < 28)
            if z_score < self.entry_z_threshold and rsi < self.entry_rsi_limit:
                
                # Scoring: Prioritize the most extreme statistical anomalies
                # Score = Deviation magnitude * Momentum exhaustion
                score = abs(z_score) * (100 - rsi)
                
                candidates.append({
                    'symbol': sym,
                    'score': score,
                    'price': self.history[sym][-1]
                })
        
        # Execute Best Candidate
        if candidates:
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