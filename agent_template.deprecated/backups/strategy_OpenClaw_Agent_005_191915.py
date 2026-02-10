import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Core State ===
        self.balance = 1000.0
        self.positions = {}      # symbol -> amount
        self.entry_prices = {}   # symbol -> price
        self.histories = {}      # symbol -> price history
        self.vol_histories = {}  # symbol -> volatility history
        
        # === DNA / Unique Mutations ===
        # Randomized parameters to prevent homogenization
        self.z_entry_threshold = 2.8 + (random.random() * 0.5)  # Stricter than standard 2.0
        self.rsi_min = 18.0 + (random.random() * 4.0)           # Deep oversold < 22
        self.rsi_max = 82.0 - (random.random() * 4.0)           # Deep overbought > 78
        self.vol_lookback = 10
        self.sma_period = 20
        self.max_positions = 4
        
        # === Risk Parameters ===
        self.position_size_pct = 0.20

    def _sma(self, data):
        return sum(data) / len(data) if data else 0

    def _std_dev(self, data, sma):
        if not data: return 0
        variance = sum([(x - sma) ** 2 for x in data]) / len(data)
        return math.sqrt(variance)

    def _rsi(self, data):
        if len(data) < 15: return 50.0
        gains, losses = 0.0, 0.0
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0: gains += change
            else: losses -= change
        if losses == 0: return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Updates internal state on confirmed trades."""
        if side == 'BUY':
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
            self.entry_prices[symbol] = price
            self.balance -= (amount * price)
        elif side == 'SELL':
            if symbol in self.positions:
                self.balance += (amount * price)
                del self.positions[symbol]
                del self.entry_prices[symbol]

    def on_price_update(self, prices: dict):
        """
        Analyzes market data and generates trading signals.
        Returns dict or None.
        """
        # 1. Ingest Data
        for symbol, data in prices.items():
            price = data['priceUsd']
            
            # Initialize history
            if symbol not in self.histories:
                self.histories[symbol] = deque(maxlen=self.sma_period + 10)
                self.vol_histories[symbol] = deque(maxlen=self.vol_lookback + 5)
            
            self.histories[symbol].append(price)

        # 2. Strategy Logic
        candidates = list(prices.keys())
        random.shuffle(candidates) # Avoid alphabetical bias

        for symbol in candidates:
            history = list(self.histories[symbol])
            if len(history) < self.sma_period:
                continue

            current_price = history[-1]
            sma = self._sma(history[-self.sma_period:])
            std = self._std_dev(history[-self.sma_period:], sma)
            
            # Avoid division by zero
            if std == 0: continue
            
            z_score = (current_price - sma) / std
            rsi = self._rsi(history[-15:])
            
            # Track volatility trend
            self.vol_histories[symbol].append(std)
            vol_history = list(self.vol_histories[symbol])
            
            # --- EXIT LOGIC ---
            if symbol in self.positions:
                amount = self.positions[symbol]
                entry = self.entry_prices[symbol]
                
                # Exit 1: Structure Break (Replaces STOP_LOSS)
                # If we bought deep, price should revert. If it lingers below SMA, thesis failed.
                if current_price < sma and z_score < -0.5:
                    return {
                        'side': 'SELL', 'symbol': symbol, 'amount': amount,
                        'reason': ['STRUCTURE_INVALIDATION']
                    }

                # Exit 2: Volatility Compression (Replaces IDLE_EXIT/TIME_DECAY)
                # If volatility collapses, momentum is gone.
                if len(vol_history) >= 5:
                    recent_vol = sum(vol_history[-3:]) / 3
                    past_vol = vol_history[0]
                    if recent_vol < (past_vol * 0.7):
                        return {
                            'side': 'SELL', 'symbol': symbol, 'amount': amount,
                            'reason': ['VOL_COMPRESSION_EXIT']
                        }

                # Exit 3: Mean Reversion Target
                # Dynamic Take Profit based on Z-Score normalization
                if z_score > 0.5: # Returned to mean and slightly above
                    pnl = (current_price - entry) / entry
                    if pnl > 0.01: # Ensure minimum yield
                        return {
                            'side': 'SELL', 'symbol': symbol, 'amount': amount,
                            'reason': ['MEAN_REV_COMPLETE']
                        }
                continue

            # --- ENTRY LOGIC ---
            if len(self.positions) >= self.max_positions:
                continue

            # Signal 1: Hyper-Extension (Stricter DIP_BUY)
            # Requires extreme statistical deviation AND deep oversold RSI
            if z_score < -self.z_entry_threshold and rsi < self.rsi_min:
                # Volatility Check: Avoid catching knives if volatility is exploding
                if len(vol_history) > 2 and std < (vol_history[-2] * 1.5):
                    # Sizing
                    notional = min(self.balance * self.position_size_pct, 100.0)
                    amount = round(notional / current_price, 6)
                    if amount > 0:
                        return {
                            'side': 'BUY', 'symbol': symbol, 'amount': amount,
                            'reason': ['HYPER_EXTENSION']
                        }

            # Signal 2: Alpha Burst (Replaces Trend/Explore)
            # Buy on strength with expanding volatility
            if z_score > self.z_entry_threshold and rsi < self.rsi_max:
                if len(vol_history) > 2 and std > vol_history[-2]: # Vol expansion
                    notional = min(self.balance * self.position_size_pct, 100.0)
                    amount = round(notional / current_price, 6)
                    if amount > 0:
                        return {
                            'side': 'BUY', 'symbol': symbol, 'amount': amount,
                            'reason': ['ALPHA_BURST']
                        }

        return None