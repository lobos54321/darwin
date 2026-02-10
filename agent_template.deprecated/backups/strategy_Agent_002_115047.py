import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Increased window size for robust statistical baseline
        self.history = {}
        self.history_window = 60
        self.rsi_period = 14
        
        # Hyper-Strict Thresholds (Fixing 'DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE' Penalties)
        # Moving from "Oversold" to "Statistical Anomaly" territory.
        self.rsi_entry_threshold = 12.0  # Lowered from 20 to 12 (Extreme outlier only)
        self.z_score_threshold = -3.2    # Deepened from -2.8 to -3.2 (Capture >3 SD events)
        self.min_volatility = 0.005      # Increased volatility requirement
        self.risk_amount = 20.0

    def _calculate_rsi(self, prices):
        """Calculates RSI to detect structural market weakness."""
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
        """
        Analyzes market data for extreme statistical deviations with strict reversal confirmation.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            current_price = prices[symbol]['priceUsd']
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            
            # Ensure sufficient data for Z-Score (20) and RSI (14)
            if len(self.history[symbol]) < 25:
                continue

            recent_prices = list(self.history[symbol])
            
            # --- Statistical Calculations ---
            sma_window = recent_prices[-20:]
            sma = statistics.mean(sma_window)
            stdev = statistics.stdev(sma_window)
            
            if stdev == 0:
                continue

            z_score = (current_price - sma) / stdev
            rsi = self._calculate_rsi(recent_prices)
            volatility_ratio = (4 * stdev) / sma

            # --- Logic: EXTREME MEAN REVERSION ---
            # Addressed Penalties:
            # 1. Stricter Z-Score (< -3.2) ensures we only buy significant crashes, not standard dips.
            # 2. Stricter RSI (< 12) prevents buying early in a downtrend.
            
            is_anomaly_low = z_score < self.z_score_threshold
            is_structurally_collapsed = rsi < self.rsi_entry_threshold
            is_volatile = volatility_ratio > self.min_volatility

            if is_anomaly_low and is_structurally_collapsed and is_volatile:
                
                # CONFIRMATION: Micro-Trend Reversal
                # Prevent "Falling Knife" by ensuring the immediate down-move has paused.
                # 1. Current price must be higher than previous price.
                # 2. Previous price must be lower/equal to the one before (confirming a local bottom).
                
                p_now = recent_prices[-1]
                p_prev = recent_prices[-2]
                p_prev_2 = recent_prices[-3]
                
                is_reversing = (p_now > p_prev) and (p_prev <= p_prev_2)

                if is_reversing:
                    # Target Mean Reversion
                    take_profit = sma
                    # Stop loss set wide to accommodate volatility tail risks
                    stop_loss = current_price - (stdev * 4.0) 

                    return {
                        'symbol': symbol,
                        'side': 'BUY',
                        'amount': self.risk_amount,
                        'take_profit': take_profit,
                        'stop_loss': stop_loss,
                        'reason': ['EXTREME_ANOMALY', 'Z_SCORE_3SD']
                    }
        
        return None