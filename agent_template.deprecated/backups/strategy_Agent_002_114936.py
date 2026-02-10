import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Increased strictness to mitigate 'falling knife' risks
        self.history = {}
        self.history_window = 50
        self.rsi_period = 14
        
        # Stricter Thresholds (Fixing Penalized Logic)
        self.rsi_threshold = 20       # Lowered from 27 to 20 (Hard Oversold)
        self.z_entry_threshold = -2.8 # Deepened from -2.2 to -2.8
        self.min_volatility = 0.002
        self.risk_amount = 25.0

    def _calculate_rsi(self, prices):
        """Standard RSI calculation."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Use only the window needed for RSI
        window = list(prices)[-(self.rsi_period + 1):]
        gains = []
        losses = []
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        if not gains and not losses:
            return 50.0
            
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
            
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices):
        """
        Analyzes price updates for deep value setups with strict confirmation.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols) # Avoid alphabet bias
        
        for symbol in symbols:
            current_price = prices[symbol]['priceUsd']
            
            # Maintain History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            
            # Need sufficient data for SMA(20) and RSI(14)
            if len(self.history[symbol]) < 21:
                continue

            # --- Statistical Analysis ---
            # Last 20 periods for Bollinger/Z-Score
            recent_prices = list(self.history[symbol])
            sma_window = recent_prices[-20:]
            
            sma = statistics.mean(sma_window)
            stdev = statistics.stdev(sma_window)
            
            # Skip if flatline
            if stdev == 0:
                continue

            z_score = (current_price - sma) / stdev
            rsi = self._calculate_rsi(recent_prices)
            band_width = (4 * stdev) / sma

            # --- logic: PRECISION MEAN REVERSION ---
            # Fixed Penalized Logic:
            # 1. RSI must be < 20 (Extreme oversold, was 30)
            # 2. Z-Score must be < -2.8 (3 Sigma deviation event, was -2.2)
            # 3. Volatility must exist (Avoid dead assets)
            
            is_extreme_oversold = rsi < self.rsi_threshold
            is_significant_dip = z_score < self.z_entry_threshold
            has_volatility = band_width > self.min_volatility

            if is_extreme_oversold and is_significant_dip and has_volatility:
                
                # CONFIRMATION LAYER:
                # Don't buy the red candle. Wait for a green tick that reclaims some ground.
                # Current price must be higher than previous price to prove buyers are stepping in.
                prev_price = recent_prices[-2]
                
                if current_price > prev_price:
                    # Calculate dynamic TP/SL
                    # TP: Return to Mean (SMA)
                    # SL: 3 Stdevs down (Wide room for volatility)
                    take_profit = sma
                    stop_loss = current_price - (stdev * 3.0) 

                    return {
                        'symbol': symbol,
                        'side': 'BUY',
                        'amount': self.risk_amount,
                        'take_profit': take_profit,
                        'stop_loss': stop_loss,
                        'reason': ['PRECISION_REV', 'EXTREME_RSI']
                    }
        
        return None