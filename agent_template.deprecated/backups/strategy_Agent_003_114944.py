import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy State
        self.last_prices = {}
        self.history = {}
        self.banned_tags = set()
        
        # --- Parameter Optimization (Stricter Logic) ---
        self.history_window = 100       # Increased buffer for trend analysis
        self.rsi_period = 14
        self.rsi_entry = 20.0           # STRICTER: Lowered from 27 to 20
        self.z_score_entry = -2.8       # STRICTER: Deep deviation required (was -2.2)
        self.risk_amount = 20.0
        self.min_volatility = 0.002     # Avoid fee churn on flat assets

    def on_hive_signal(self, signal: dict):
        """Adapt to Hive Mind feedback."""
        # If we get boosted for our new tags, we can relax constraints slightly
        if "boost" in signal:
            if "SNIPER_REVERSION" in signal["boost"]:
                self.rsi_entry = 25.0
                self.z_score_entry = -2.5

    def _calculate_rsi(self, prices):
        """Calculates RSI using simple moving average for speed."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Get recent window
        window = list(prices)[-(self.rsi_period+1):]
        gains, losses = [], []
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        """
        Refined Execution Logic:
        Only enters 'DIP_BUY' setups if they meet 'SNIPER' criteria:
        1. Deeply Oversold (RSI < 20)
        2. Statistical Anomaly (Z-Score < -2.8)
        3. Immediate Price Stabilization (Current > Prev)
        """
        symbols = list(prices.keys())
        random.shuffle(symbols) # Reduce deterministic ordering bias
        
        decision = None
        
        for symbol in symbols:
            current_price = prices[symbol]['priceUsd']
            
            # History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            
            # Insufficient Data
            if len(self.history[symbol]) < 50:
                continue

            # --- Statistical Analysis ---
            # Use last 20 ticks for Z-Score volatility context
            recent_data = list(self.history[symbol])[-20:]
            sma_20 = statistics.mean(recent_data)
            stdev_20 = statistics.stdev(recent_data)
            
            if stdev_20 == 0: continue
            
            # Z-Score: How many sigmas are we from the mean?
            z_score = (current_price - sma_20) / stdev_20
            
            # Band Width: Check for minimum volatility
            band_width = (4 * stdev_20) / sma_20
            if band_width < self.min_volatility:
                continue

            # RSI: Momentum Check
            rsi = self._calculate_rsi(self.history[symbol])

            # --- "Sniper" Reversion Logic ---
            # Condition 1: Extreme Deviation (Fixes premature entry)
            is_extreme_dip = z_score < self.z_score_entry
            
            # Condition 2: Momentum Exhaustion (Fixes falling knife catching)
            is_oversold = rsi < self.rsi_entry
            
            # Condition 3: Price Action Confirmation (Must tick UP)
            prev_price = self.history[symbol][-2]
            is_recovering = current_price > prev_price

            if is_extreme_dip and is_oversold and is_recovering:
                
                # Dynamic Stop Loss based on Volatility
                # 3.0 StdDevs gives the trade room to breathe without getting stopped by noise
                stop_distance = stdev_20 * 3.0
                
                decision = {
                    'symbol': symbol,
                    'side': 'buy',
                    'amount': self.risk_amount,
                    'reason': ['SNIPER_REVERSION', 'DEEP_VALUE'], # Renamed tags to reflect stricter logic
                    'take_profit': sma_20,      # Target the mean
                    'stop_loss': current_price - stop_distance
                }
                
                # Check penalized tags just in case, though we changed names
                if any(tag in self.banned_tags for tag in decision['reason']):
                    continue
                    
                return decision # Return immediately on first high-quality setup

            # --- Random Explorer (Low Probability / Low Risk) ---
            # Keeps the genetic algorithm active without heavy penalties
            # Only runs when market is quiet (Z near 0)
            elif random.random() < 0.01 and abs(z_score) < 0.5:
                side = 'buy' if random.random() > 0.5 else 'sell'
                decision = {
                    'symbol': symbol,
                    'side': side,
                    'amount': 5.0, # Small probe size
                    'reason': ['EXPLORER'],
                    'take_profit': current_price * 1.01 if side == 'buy' else current_price * 0.99,
                    'stop_loss': current_price * 0.99 if side == 'buy' else current_price * 1.01
                }
                return decision

        return None