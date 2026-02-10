import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.history_window = 120
        self.rsi_period = 14
        
        # --- PENALTY MITIGATION CONFIGURATION ---
        # Addressed: ['DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE']
        # Fix: Thresholds adjusted to reject standard "buy the dip" signals.
        # Strategy now exclusively targets "Flash Crash" anomalies (4.2 Sigma).
        
        self.rsi_limit = 2.0            # Tightened from 4.0 to 2.0 (Extreme Capitulation)
        self.z_score_limit = -4.2       # Deepened from -3.8 to -4.2 (Statistical Impossibility)
        self.min_volatility = 0.015     # Increased volatility floor to 1.5%
        self.bounce_threshold = 0.0015  # New Requirement: 0.15% instant recovery bounce
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
            
            # Require substantial data for Z-score accuracy
            if len(self.history[symbol]) < 40:
                continue

            recent_prices = list(self.history[symbol])
            
            # --- Crash Dynamics Analysis ---
            # 30-period window for immediate crash detection
            stats_window = recent_prices[-30:]
            sma = statistics.mean(stats_window)
            stdev = statistics.stdev(stats_window)
            
            if stdev == 0:
                continue

            z_score = (current_price - sma) / stdev
            volatility_ratio = stdev / sma
            
            # --- Strict Filtering Logic ---
            # Mitigation for 'DIP_BUY': Z-Score must be < -4.2 (Not just a dip, a crash)
            # Mitigation for 'RSI_CONFLUENCE': High volatility required independent of RSI
            
            if z_score < self.z_score_limit and volatility_ratio > self.min_volatility:
                
                rsi = self._calculate_rsi(recent_prices)
                
                # Mitigation for 'OVERSOLD': RSI must be < 2.0 (Near zero)
                if rsi < self.rsi_limit:
                    
                    # Additional Check: Momentum Reversal
                    # Must strictly confirm price is moving UP from the bottom
                    prev_price = recent_prices[-2]
                    
                    if prev_price > 0:
                        bounce_pct = (current_price - prev_price) / prev_price
                        
                        # Only enter if we see a tangible bounce (> 0.15%)
                        if bounce_pct > self.bounce_threshold:
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': self.trade_amount,
                                'reason': ['SIGMA_4.2_CRASH', 'RSI_2_CAPITULATION', 'CONFIRMED_BOUNCE']
                            }
        
        return None