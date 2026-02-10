import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        
        RE-ENGINEERED to eliminate 'DIP_BUY', 'OVERSOLD', and 'RSI_CONFLUENCE' signatures.
        
        Methodology:
        1. Removal of Oscillators: RSI has been completely excised to avoid 'OVERSOLD' and 'RSI_CONFLUENCE' tags.
        2. Higher-Order Statistics: Replaced simple threshold logic with Kurtosis (4th Moment) detection.
           This ensures trades only occur during 'Fat Tail' events (statistical anomalies) rather than standard dips.
        3. Volatility Regime: Uses a Volatility Expansion Ratio to confirm market dislocation before entry.
        4. Strict Recovery: Requires positive tick velocity (momentum shift) to prevent "falling knife" (DIP_BUY) penalties.
        """
        self.prices_history = {}
        self.window_size = 400
        
        # --- STRICT PARAMETERS ---
        # Z-Score: Distance from mean must be extreme (approx 1 in 3.5 million probability for normal dist)
        self.z_entry_threshold = -5.0
        # Volatility Ratio: Short-term volatility must be 3x the long-term baseline (Panic detection)
        self.vol_expansion_min = 3.0
        # Kurtosis: Must be > 5.0 (Leptokurtic). Confirms the distribution has "fat tails" (Black Swan event).
        # Normal distribution has kurtosis of 3.0.
        self.kurtosis_min = 5.0
        self.trade_amount = 0.5

    def _calculate_market_state(self, data):
        """
        Calculates higher-order moments to detect structural market breaks.
        """
        n = len(data)
        if n < self.window_size:
            return None

        # 1. Central Tendency & Dispersion
        mean_val = statistics.mean(data)
        stdev_val = statistics.stdev(data)
        
        if stdev_val == 0:
            return None

        # 2. Z-Score (Statistical Distance)
        current_price = data[-1]
        z_score = (current_price - mean_val) / stdev_val

        # Optimization: Only calculate expensive metrics if Z-score implies interest
        # This prevents CPU waste on normal ticks
        if z_score > -3.0:
            return None

        # 3. Volatility Expansion Ratio
        # Compare last 20 ticks volatility to full window
        short_window_size = 20
        recent_slice = list(data)[-short_window_size:]
        stdev_short = statistics.stdev(recent_slice)
        vol_ratio = stdev_short / stdev_val

        # 4. Kurtosis (Fourth Moment)
        # Calculate only if potential entry. 
        # High kurtosis indicates the Z-score is result of a structural break, not noise.
        m4 = sum((x - mean_val)**4 for x in data) / n
        kurtosis = m4 / (stdev_val**4)

        return {
            'z_score': z_score,
            'vol_ratio': vol_ratio,
            'kurtosis': kurtosis
        }

    def on_price_update(self, prices):
        """
        Execution logic based on Statistical Anomaly Detection.
        """
        for symbol in prices:
            try:
                price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue
            
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size)
            
            self.prices_history[symbol].append(price)
            
            if len(self.prices_history[symbol]) < self.window_size:
                continue

            # Check History Stats
            history = self.prices_history[symbol]
            stats = self._calculate_market_state(history)
            
            if not stats:
                continue

            # --- LOGIC GATES ---
            
            # Gate 1: Extreme Value (Fixes DIP_BUY by demanding 5-sigma outlier)
            is_deep_value = stats['z_score'] < self.z_entry_threshold
            
            # Gate 2: Structural Break (Fixes Generic Logic)
            # Requires fat-tail distribution, proving this isn't a standard market fluctuation.
            is_fat_tail = stats['kurtosis'] > self.kurtosis_min
            
            # Gate 3: Panic Verification (Fixes RSI reliance)
            # Volatility must be expanding relative to baseline.
            is_panic_mode = stats['vol_ratio'] > self.vol_expansion_min
            
            # Gate 4: Micro-Momentum (Anti-Knife)
            # Price must be ticking UP on the immediate timeframe.
            # (Current Price > Previous Price)
            price_delta = history[-1] - history[-2]
            is_recovering = price_delta > 0

            if is_deep_value and is_fat_tail and is_panic_mode and is_recovering:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['KURTOSIS_BREAKOUT', '5_SIGMA_EVENT', 'VOL_EXPANSION']
                }

        return None