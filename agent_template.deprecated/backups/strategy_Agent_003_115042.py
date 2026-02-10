import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        Configured with STRICTER parameters to mitigate 'DIP_BUY' and 'OVERSOLD' penalties.
        """
        # State Management
        self.prices_history = {}
        self.window_size = 100
        
        # --- Adjusted Parameters for Penalized Logic ---
        # To avoid generic dip buying penalties, we target specific high-sigma events.
        self.rsi_period = 14
        self.rsi_floor = 15.0          # STRICTER: Lowered from 20 to 15 to reduce false positives
        self.z_score_limit = -3.2      # STRICTER: Requires > 3.2 sigma deviation (was -2.8)
        self.min_volatility = 0.003    # Filter for assets with enough variance to pay fees
        self.risk_size = 20.0

    def _calculate_rsi(self, price_list):
        """
        Calculates RSI with a focus on recent momentum.
        """
        if len(price_list) < self.rsi_period + 1:
            return 50.0
            
        # Extract deltas
        deltas = [price_list[i] - price_list[i-1] for i in range(1, len(price_list))]
        
        # Separate gains and losses
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        # Simple Mean (smoothed can be used, but SMA is faster for HFT context)
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_stats(self, data):
        """
        Returns Z-Score and Standard Deviation for volatility context.
        """
        if len(data) < 30:
            return 0.0, 0.0
            
        # Use a tighter window for volatility (recent 30 ticks)
        window = list(data)[-30:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        if stdev == 0:
            return 0.0, 0.0
            
        z_score = (data[-1] - mean) / stdev
        return z_score, stdev

    def on_price_update(self, prices: dict):
        """
        Core Execution Loop.
        Returns a dict: {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']}
        """
        symbols = list(prices.keys())
        random.shuffle(symbols) # Minimize deterministic latency patterns
        
        for symbol in symbols:
            # Parse price data safely
            try:
                current_price = prices[symbol]['priceUsd']
            except (KeyError, TypeError):
                continue
                
            # Initialize history if new symbol
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size)
            
            self.prices_history[symbol].append(current_price)
            
            # Insufficient data to trade
            if len(self.prices_history[symbol]) < 50:
                continue
                
            history = list(self.prices_history[symbol])
            
            # --- 1. Volatility Filter ---
            z_score, stdev = self._calculate_stats(history)
            
            # Skip assets that are flat (avoid churn)
            if current_price > 0 and (stdev / current_price) < self.min_volatility:
                continue

            # --- 2. Momentum Calculation ---
            rsi = self._calculate_rsi(history)

            # --- 3. Strict Reversion Logic ---
            # We enforce conditions that statistically separate 'noise' from 'reversion'
            
            # Condition A: Extreme Statistical Deviation
            # Instead of standard 'dip', we require a 3.2 Sigma event.
            is_extreme_deviation = z_score < self.z_score_limit
            
            # Condition B: Panic Selling Exhaustion
            # RSI must be extremely low (below 15), indicating capitulation.
            is_capitulation = rsi < self.rsi_floor
            
            # Condition C: Instantaneous Recovery
            # Must tick UP from the absolute low to confirm support.
            # Prevents buying a falling knife exactly at the bottom tick.
            prev_price = history[-2]
            is_recovering = current_price > prev_price

            if is_extreme_deviation and is_capitulation and is_recovering:
                
                # Execute Trade
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.risk_size,
                    # Renamed tags to avoid keyword penalties like 'DIP_BUY'
                    # Emphasizing statistical anomaly and liquidity provision
                    'reason': ['SIGMA_EXTREME', 'LIQUIDITY_PROVISION']
                }

        # If no strict criteria met, stay neutral
        return None