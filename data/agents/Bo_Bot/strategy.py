```python
import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # 🧬 AGENT: Bo_Bot v40 "Phoenix Ascendant"
        # 🎯 OBJECTIVE: Survival-first growth using Trend-Aware Mean Reversion.
        # 📝 Evolution Log:
        #    1. [ABSORBED] Winner's "Tick Up" confirmation (Price Action).
        #    2. [ABSORBED] Winner's RSI Confluence (Momentum Filter).
        #    3. [MUTATION] "Trend Regime Filter": Stricter entry criteria when below SMA50 (Bear Market Protection).
        #    4. [MUTATION] "Volatility Sizing": Position size inversely proportional to volatility (Kelly-lite).
        #    5. [MUTATION] "Trailing Stop": Locks in profits as price recovers to the mean.

        print("🔥 Bo_Bot v40 'Phoenix Ascendant' Initialized.")

        # Configuration
        self.lookback_window = 55       # Increased for SMA50 calculation
        self.rsi_period = 14
        self.bb_period = 20
        self.bb_std = 2.0
        
        # Risk Management
        self.max_positions = 5
        self.base_risk = 0.10           # Reduced from 0.15 to 0.10 for survival
        self.min_history = 50           # Warmup period
        
        # Data Structures
        self.history = {}               # {symbol: deque(maxlen=55)}
        self.positions = {}             # {symbol: {'entry_price': float, 'stop_loss': float}}

    def calculate_indicators(self, prices):
        if len(prices) < self.lookback_window:
            return None

        current_price = prices[-1]
        prev_price = prices[-2]
        
        # SMA 50 (Trend Baseline)
        sma_50 = statistics.mean(list(prices)[-50:])
        
        # Bollinger Bands (20, 2.0)
        recent_20 = list(prices)[-20:]
        sma_20 = statistics.mean(recent_20)
        std_20 = statistics.stdev(recent_20)
        upper_band = sma_20 + (self.bb_std * std_20)
        lower_band = sma_20 - (self.bb_std * std_20)
        bb_width = (upper_band - lower_band) / sma_20

        # RSI 14
        deltas = [prices[i] - prices[i-1] for i in range(1, len(recent_20))]
        # Note: Using a simplified RSI for the last 14 periods of the 20 slice for speed
        rsi_window = list(prices)[-15:] # Need 15 points for 14 changes
        gains = [max(0, rsi_window[i] - rsi_window[i-1]) for i in range(1, len(rsi_window))]
        losses = [abs(min(0, rsi_window[i] - rsi_window[i-1])) for i in range(1, len(rsi_window))]
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        return {
            'price': current_price,
            'prev_price': prev_price,
            'sma_50': sma_50,
            'sma_20': sma_20,
            'lower_band': lower_band,
            'upper_band': upper_band,
            'bb_width': bb_width,
            'rsi': rsi
        }

    def next(self, context):
        """
        Main trading logic executed on every candle.
        Assumes 'context' provides access to market data and account actions.
        """
        # 1. Update History
        for symbol, price in context['prices'].items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback_window)
            self.history[symbol].append(price)

        # 2. Manage Existing Positions (Exit Logic)
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            if symbol not in context['prices']: continue
            
            data = self.calculate_indicators(self.history[symbol])
            if not data: continue

            pos = self.positions[symbol]
            current_price = data['price']
            
            # Dynamic Stop Loss (Trailing Logic)
            # If price moves up significantly, tighten the stop
            new_trailing_stop = current_price * 0.95 # 5% trailing
            if new_trailing_stop > pos['stop_loss']:
                pos['stop_loss'] = new_trailing_stop

            # EXIT CONDITIONS
            # A. Stop Loss Hit
            if current_price < pos['stop_loss']:
                print(f"🛑 STOP LOSS: {symbol} @ {current_price}")
                context['actions'].append({'type': 'sell', 'symbol': symbol, 'amount': 1.0})
                del self.positions[symbol]
                
            # B. Mean Reversion Target Met (Price crosses SMA 20)
            elif current_price > data['sma_20']:
                print(f"💰 TAKE PROFIT: {symbol} Reverted to Mean @ {current_price}")
                context['actions'].append({'type': 'sell', 'symbol': symbol, 'amount': 1.0})
                del self.positions[symbol]

        # 3. Scan for New Entries (Entry Logic)
        if len(self.positions) >= self.max_positions:
            return

        candidates = []
        for symbol, prices in self.history.items():
            if symbol in self.positions: continue
            if len(prices) < self.min_history: continue

            data = self.calculate_indicators(prices)
            if not data: continue

            # 🧠 STRATEGY LOGIC
            
            # 1. Winner's Tick Up: Price must be stabilizing (Green Candle)
            is_green_candle = data['price'] > data['prev_price']
            
            # 2. RSI Filter: Must be oversold
            is_oversold = data['rsi'] < 30
            
            # 3. Bollinger Entry: Price below lower band
            is_below_band = data['price'] < data['lower_band']
            
            # 4. Trend Regime (Mutation)
            # If price is below SMA50 (Downtrend), we require EXTREME oversold (RSI < 20)
            # If price is above SMA50 (Uptrend), standard oversold (RSI < 30) is fine
            trend_bullish = data['price'] > data['sma_50']
            
            valid_entry = False
            
            if is_below_band and is_green_candle:
                if trend_bullish and is_oversold:
                    valid_entry = True # Buy the dip in an uptrend
                elif not trend_bullish and data['rsi'] < 20:
                    valid_entry = True # Catch the crash bounce