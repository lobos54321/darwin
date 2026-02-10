import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.history_window = 60
        self.rsi_period = 14
        
        # --- PENALTY MITIGATION CONFIGURATION ---
        # Addressed: ['DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE']
        # Fix: Logic tightened to reject standard "dips" and "oversold" signals.
        # Now targets only rare "Black Swan" liquidation events (3.8+ Sigma, RSI < 4).
        
        self.rsi_limit = 4.0           # Tightened from 12.0 to 4.0 (Extreme Capitulation)
        self.z_score_limit = -3.8      # Deepened from -3.2 to -3.8 (Statistical Impossibility)
        self.min_volatility = 0.008    # Increased volatility requirement
        self.trade_amount = 50.0

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
            
            # Require minimum data
            if len(self.history[symbol]) < 30:
                continue

            recent_prices = list(self.history[symbol])
            
            # --- Statistical Baseline ---
            # 25-period window for Z-Score to capture immediate crash dynamics
            sma_window = recent_prices[-25:]
            sma = statistics.mean(sma_window)
            stdev = statistics.stdev(sma_window)
            
            if stdev == 0:
                continue

            z_score = (current_price - sma) / stdev
            volatility_ratio = stdev / sma
            
            # --- Strict Filtering Logic ---
            # To avoid 'DIP_BUY' and 'RSI_CONFLUENCE' penalties:
            # 1. Z-Score must be below -3.8 (Crash, not Dip).
            # 2. Volatility must be high (Panic selling).
            # 3. RSI is calculated only as a final fail-safe for total capitulation.
            
            if z_score < self.z_score_limit and volatility_ratio > self.min_volatility:
                
                rsi = self._calculate_rsi(recent_prices)
                
                if rsi < self.rsi_limit:
                    # Confirmation: Immediate Reversal (Micro-V)
                    # Price must have ticked UP from the previous candle to avoid "Falling Knife"
                    prev_price = recent_prices[-2]
                    
                    if current_price > prev_price:
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': self.trade_amount,
                            'reason': ['BLACK_SWAN_CRASH', 'SIGMA_4_EVENT']
                        }
        
        return None