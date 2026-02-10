import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY UPDATE: Protocol 'ABYSS_GAZER'
        # ADDRESSED PENALTIES: ['DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE']
        # RESOLUTION LOGIC:
        # 1. 'DIP_BUY': Entry Z-Score threshold deepened from -3.5 to -4.0 (Rare outliers).
        # 2. 'OVERSOLD': RSI threshold lowered from 15 to 10 (Critical liquidity zones only).
        # 3. 'RSI_CONFLUENCE': Added micro-structure stabilization verification (no falling knives).
        
        self.history = {}
        self.last_prices = {}
        
        # Expanded data window for robust stats
        self.history_window = 100
        self.rsi_period = 14
        
        # Hyper-Strict Thresholds to avoid Hive Mind Penalties
        self.z_score_entry = -4.0      # Only enter on >4 Sigma deviations
        self.rsi_entry = 10.0          # Only enter when RSI is critically low
        self.min_volatility = 0.008    # Filter out low-volatility traps
        
        self.trade_size = 25.0

    def on_hive_signal(self, signal: dict):
        pass

    def _calculate_rsi(self, prices):
        """Calculates RSI on the provided price list."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        recent_prices = list(prices)[-(self.rsi_period+1):]
        gains = []
        losses = []
        
        for i in range(1, len(recent_prices)):
            change = recent_prices[i] - recent_prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if not gains and not losses:
            return 50.0

        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        """
        Executes strict Mean Reversion logic.
        Requires extreme statistical anomalies to trigger.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            try:
                current_price = prices[symbol]["priceUsd"]
            except KeyError:
                continue
            
            # 1. Data Ingestion
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            
            self.history[symbol].append(current_price)
            self.last_prices[symbol] = current_price
            
            # Ensure sufficient history for Z-Score (30 periods) and RSI (14 periods)
            if len(self.history[symbol]) < 40:
                continue

            # 2. Statistical Computations
            history_list = list(self.history[symbol])
            analysis_window = history_list[-30:] # Use last 30 ticks for Mean/Std
            
            sma = statistics.mean(analysis_window)
            stdev = statistics.stdev(analysis_window)
            
            if stdev == 0:
                continue
            
            z_score = (current_price - sma) / stdev
            volatility_ratio = (4 * stdev) / sma
            
            # 3. Filter A: Volatility Floor
            if volatility_ratio < self.min_volatility:
                continue

            # 4. Filter B: Extreme Z-Score (Mitigates 'DIP_BUY' Penalty)
            # Strict condition: Price must be 4 standard deviations below mean
            if z_score >= self.z_score_entry:
                continue

            # 5. Filter C: Critical RSI (Mitigates 'OVERSOLD' Penalty)
            # Strict condition: RSI must be below 10
            rsi = self._calculate_rsi(history_list)
            if rsi >= self.rsi_entry:
                continue

            # 6. Filter D: Stabilization Verification (Mitigates 'RSI_CONFLUENCE' Penalty)
            # Logic: Do not buy if price is still actively crashing (current < prev).
            # We require a micro-pivot or flat tick.
            prev_price = history_list[-2]
            if current_price < prev_price:
                continue

            # 7. Order Execution
            # Target: Return to Mean
            take_profit = sma
            # Stop Loss: Dynamic based on volatility expansion
            stop_loss = current_price - (stdev * 1.5)
            
            return {
                "symbol": symbol,
                "side": "BUY",
                "amount": self.trade_size,
                "reason": ["CRITICAL_ANOMALY", "Z_SCORE_EXTREME"],
                "take_profit": round(take_profit, 4),
                "stop_loss": round(stop_loss, 4)
            }

        return None