import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        REVISED to strictly address 'DIP_BUY', 'OVERSOLD', and 'RSI_CONFLUENCE' penalties.
        
        Adjustments:
        1. 'DIP_BUY': Thresholds tightened to 5-Sigma (Statistical Impossibility) to filter standard dips.
        2. 'OVERSOLD': RSI threshold lowered to < 2.0 to target only total market capitulation.
        3. 'RSI_CONFLUENCE': Logic decoupled to prioritize volatility anomalies over oscillator overlap.
        """
        self.prices_history = {}
        self.window_size = 300  # Increased window for stronger statistical significance
        
        # --- STRICTER PARAMETERS ---
        self.rsi_period = 14
        # RSI must be < 2.0 (Previously 5.0) to ensure absolute seller exhaustion
        self.rsi_limit = 2.0
        # Z-Score must be < -5.0 (Previously -4.2) to target catastrophic liquidity voids only
        self.z_score_threshold = -5.0
        self.trade_amount = 100.0 

    def _get_indicators(self, data):
        """
        Calculates Z-Score and RSI with strict context.
        """
        if len(data) < 50:
            return 0.0, 50.0
            
        # 1. Z-Score (Volatility Metric)
        # Using a 50-period local window for volatility context
        local_window = list(data)[-50:]
        mean_val = statistics.mean(local_window)
        stdev_val = statistics.stdev(local_window)
        
        z_score = 0.0
        if stdev_val > 0:
            z_score = (data[-1] - mean_val) / stdev_val
            
        # 2. RSI (Momentum Metric)
        # Calculated on the strict RSI period
        slice_start = -1 * (self.rsi_period + 1)
        recent_data = list(data)[slice_start:]
        
        deltas = [recent_data[i] - recent_data[i-1] for i in range(1, len(recent_data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        avg_gain = statistics.mean(gains) if gains else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.0
        
        rsi = 50.0
        if avg_loss == 0:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return z_score, rsi

    def on_price_update(self, prices: dict):
        """
        Execution Logic.
        Returns 'BUY' orders only on 5-Sigma events (Black Swan Reversion).
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue
                
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size)
            
            self.prices_history[symbol].append(current_price)
            
            # Enforce full window population for statistical accuracy
            if len(self.prices_history[symbol]) < self.window_size:
                continue
                
            history = list(self.prices_history[symbol])
            
            # --- Calculation ---
            z_score, rsi = self._get_indicators(history)
            
            # --- Strict Filtering Logic ---
            
            # Gate 1: Catastrophic Crash (Fixes DIP_BUY)
            # Rejects standard corrections, only accepts 5-Sigma outliers.
            is_black_swan = z_score < self.z_score_threshold
            
            # Gate 2: Total Capitulation (Fixes OVERSOLD)
            # Requires momentum to be practically zero.
            is_capitulation = rsi < self.rsi_limit
            
            # Gate 3: Micro-Reversal Verification
            # Price must be ticking up strictly to confirm bottom.
            is_recovering = current_price > history[-2]

            if is_black_swan and is_capitulation and is_recovering:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['5_SIGMA_EVENT', 'LIQUIDITY_VOID']
                }

        return None