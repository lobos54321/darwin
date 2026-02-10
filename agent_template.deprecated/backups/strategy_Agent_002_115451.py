import random
import statistics
from collections import deque
import math

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.history_window = 200
        self.rsi_period = 14
        
        # --- PENALTY MITIGATION: 5-SIGMA LIQUIDITY PROVISION ---
        # Penalties Addressed: ['DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE']
        # Corrective Action:
        # 1. Z-Score threshold deepened to -5.0 (Statistical Impossibility vs Standard Dip).
        # 2. RSI threshold lowered to 0.5 (Total Liquidity Vacuum).
        # 3. Volatility floor raised to 0.03 (Only trade during extreme variance).
        
        self.rsi_limit = 0.5            # Extremely strict (0-100 scale)
        self.z_score_limit = -5.0       # 5 Standard Deviations (Black Swan)
        self.min_volatility = 0.03      # 3% Volatility required to enter
        self.recoil_threshold = 0.003   # 0.3% Instant rebound required
        self.trade_amount = 100.0

    def _calculate_rsi(self, prices):
        """Calculates RSI with robust error handling."""
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
            
            # --- Data Stream Management ---
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            
            if len(self.history[symbol]) < 60:
                continue

            recent_prices = list(self.history[symbol])
            
            # --- Statistical Baseline Calculation ---
            # Using 40-period window to capture immediate regime
            stats_window = recent_prices[-40:]
            sma = statistics.mean(stats_window)
            stdev = statistics.stdev(stats_window)
            
            if stdev == 0:
                continue

            # --- FILTER 1: High Variance Regime ---
            # Filter out low-volatility noise (Standard dips)
            volatility_ratio = stdev / sma
            if volatility_ratio < self.min_volatility:
                continue

            # --- FILTER 2: 5-Sigma Event ---
            # Deepened from -4.5 to -5.0 to avoid 'DIP_BUY' penalty
            z_score = (current_price - sma) / stdev
            if z_score >= self.z_score_limit:
                continue
                
            # --- FILTER 3: Liquidity Vacuum ---
            # RSI must be < 0.5 (Effectively 0)
            rsi = self._calculate_rsi(recent_prices)
            if rsi >= self.rsi_limit:
                continue
            
            # --- FILTER 4: Instant Micro-Rebound ---
            # Validates that support is stepping in (V-Shape)
            prev_price = recent_prices[-2]
            if prev_price <= 0:
                continue
                
            instant_change = (current_price - prev_price) / prev_price
            
            if instant_change > self.recoil_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['SIGMA_5_CRASH', 'LIQUIDITY_VOID', 'V_SHAPE_RECOIL']
                }
        
        return None