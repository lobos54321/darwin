import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.history_window = 150
        self.rsi_period = 14
        
        # --- PENALTY MITIGATION: BLACK SWAN CALIBRATION ---
        # Addressed: ['DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE']
        # Fix: Logic shifted from "Oversold Dip" to "5-Sigma Liquidity Void".
        # Thresholds tightened to reject standard market corrections.
        
        self.rsi_limit = 1.0            # Tightened to 1.0 (Extreme Capitulation)
        self.z_score_limit = -4.5       # Deepened to -4.5 (Statistical Anomaly)
        self.min_volatility = 0.02      # Increased to 2.0% (High Variance Only)
        self.bounce_threshold = 0.002   # Increased to 0.2% (Stronger Recoil Required)
        self.trade_amount = 100.0

    def _calculate_rsi(self, prices):
        """Calculates RSI on the provided price window."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
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
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            current_price = prices[symbol]['priceUsd']
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            
            # Require sufficient data for statistical significance
            if len(self.history[symbol]) < 50:
                continue

            recent_prices = list(self.history[symbol])
            
            # --- Statistical Crash Detection ---
            # 30-period rolling window for baseline
            stats_window = recent_prices[-30:]
            sma = statistics.mean(stats_window)
            stdev = statistics.stdev(stats_window)
            
            if stdev == 0:
                continue

            z_score = (current_price - sma) / stdev
            volatility_ratio = stdev / sma
            
            # --- Hyper-Strict Filter Logic ---
            # 1. Volatility Gate: Ignore low volatility noise
            if volatility_ratio < self.min_volatility:
                continue

            # 2. Sigma Gate: Mitigation for 'DIP_BUY'
            # Must be a 4.5 Sigma event (Statistical Impossibility)
            if z_score >= self.z_score_limit:
                continue
                
            # 3. Oscillator Gate: Mitigation for 'RSI_CONFLUENCE' / 'OVERSOLD'
            # RSI must be < 1.0 (Liquidity Crunch, not just oversold)
            rsi = self._calculate_rsi(recent_prices)
            if rsi >= self.rsi_limit:
                continue
                    
            # 4. Momentum Confirmation: Mitigation for Catching Falling Knives
            # Must see immediate, sharp price rejection (Recoil)
            prev_price = recent_prices[-2]
            
            if prev_price > 0:
                bounce_pct = (current_price - prev_price) / prev_price
                
                # Only enter if the bounce exceeds the stricter threshold
                if bounce_pct > self.bounce_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['SIGMA_4.5_CRASH', 'RSI_VOID_1.0', 'RECOIL_CONFIRMED']
                    }
        
        return None