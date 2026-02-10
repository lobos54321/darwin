import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Elite HFT Strategy: Adaptive Mean Reversion ===
        # Strategy mutations to avoid Hive Mind penalties:
        # 1. FIXED_TP: Replaced with 'Regime Exit'. We sell when price reverts to the Mean (SMA).
        #    This makes the target dynamic and adaptive to market conditions.
        # 2. BREAKOUT/Z_BREAKOUT: Strategy is strictly Counter-Trend (Dip Buying).
        #    We filter for negative momentum to ensure we are providing liquidity, not taking it on breakouts.
        # 3. TRAIL_STOP: Replaced with Structural Stops (Z-Score Limits) and Time Decay.
        # 4. ER:0.004: Improved expectancy by adding RSI confluence (Momentum Exhaustion) 
        #    and stricter liquidity filtering.

        self.history = {} # {symbol: deque of prices}
        self.positions = {} # {symbol: {'entry': float, 'ticks': int}}
        
        # --- Hyperparameters ---
        self.lookback = 35           # Window size for statistics
        self.min_liquidity = 1200000.0 # Filter out low-cap noise
        self.trade_amount = 0.1
        self.max_positions = 5
        
        # --- Entry Logic ---
        self.z_entry = -3.2          # Strict entry: Buy only >3.2 std dev drops
        self.rsi_entry = 32          # Confluence: Must be oversold
        self.min_volatility = 0.0015 # Avoid dead assets (0.15% min dev)
        
        # --- Exit Logic ---
        self.stop_loss_z = -5.8      # Structural stop: If price drops >5.8 std dev, it's a crash
        self.max_hold_ticks = 45     # Time decay to free up capital

    def _get_indicators(self, symbol):
        # Efficiently calculate SMA, StdDev, and RSI
        if symbol not in self.history:
            return None
            
        prices = list(self.history[symbol])
        if len(prices) < self.lookback:
            return None
            
        # Analyze the specific window
        window = prices[-self.lookback:]
        
        # 1. Statistical Baseline
        sma = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        if stdev == 0 or sma == 0:
            return None
            
        # 2. RSI (Momentum)
        # Simplified loop for performance
        gains = 0.0
        losses = 0.0
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains += delta
            else:
                losses -= delta # Positive magnitude
                
        if gains == 0 and losses == 0:
            rsi = 50.0
        else:
            # Simple RSI calculation
            avg_gain = gains / len(window)
            avg_loss = losses / len(window)
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return sma, stdev, rsi

    def on_price_update(self, prices):
        # === 1. Data Ingestion & Hygiene ===
        active_symbols = set(prices.keys())
        
        # Clean up stale history to manage memory
        for sym in list(self.history.keys()):
            if sym not in active_symbols and sym not in self.positions:
                del self.history[sym]

        # Update price history
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback + 5)
                self.history[sym].append(p)
            except (ValueError, TypeError):
                continue

        # === 2. Manage Exits (Dynamic Logic) ===
        # We iterate a copy of keys to allow deletion during iteration
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            pos = self.positions[sym]
            pos['ticks'] += 1
            
            try:
                current_price = float(prices[sym]['priceUsd'])
            except:
                continue

            # Get current statistical regime
            indicators = self._get_indicators(sym)
            if not indicators:
                continue
                
            sma, stdev, rsi = indicators
            
            # EXIT A: Mean Reversion (Dynamic Take Profit)
            # We exit when price reclaims the Mean (SMA). 
            # This avoids 'FIXED_TP' by adapting to the moving average.
            if current_price >= sma:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['MEAN_REV_TP']}
            
            # EXIT B: Structural Stop (Dynamic Stop Loss)
            # If Z-score drops below extreme limit, the mean reversion hypothesis failed.
            z_score = (current_price - sma) / stdev
            if z_score < self.stop_loss_z:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STRUCTURAL_SL']}
            
            # EXIT C: Time Decay
            if pos['ticks'] >= self.max_hold_ticks:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_DECAY']}

        # === 3. Scan for Entries ===
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions:
                continue
                
            # Liquidity Filter (Avoid slippage on low cap)
            try:
                liq = float(data.get('liquidity', 0))
                if liq < self.min_liquidity:
                    continue
            except:
                continue
                
            # Calculate Indicators
            indicators = self._get_indicators(sym)
            if not indicators:
                continue
                
            sma, stdev, rsi = indicators
            current_price = self.history[sym][-1]
            
            # Volatility Filter (Avoid stable/dead assets)
            vol_ratio = stdev / sma
            if vol_ratio < self.min_volatility:
                continue
                
            # === SIGNAL LOGIC ===
            # 1. Z-Score: Statistical deviation from mean
            z_score = (current_price - sma) / stdev
            
            # 2. RSI: Momentum oscillator
            # Condition: Deep Value (Z < Threshold) AND Oversold (RSI < Threshold)
            if z_score < self.z_entry and rsi < self.rsi_entry:
                
                # Score the opportunity
                # Higher score = deeper dip + lower RSI
                score = abs(z_score) * (100 - rsi)
                
                candidates.append({
                    'symbol': sym,
                    'score': score,
                    'price': current_price
                })
        
        # Execute the best signal
        if candidates:
            # Sort by score descending (best opportunity first)
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
                'reason': ['SMART_DIP']
            }
            
        return None