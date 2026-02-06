import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧬 AGENT: Bo_Bot | GEN: 97 | CODENAME: PHOENIX_MOMENTUM")
        print("📝 Evolution: Inherited RSI+BB (Agent_008). Added Trend Filter & Time-Decay Exit.")
        
        # --- Configuration ---
        self.balance = 1000.0  # Tracking locally if SDK doesn't provide
        self.positions = {}    # {symbol: {'entry': float, 'size': float, 'ticks_held': int, 'stop': float}}
        
        # --- Hyperparameters ---
        self.LOOKBACK_WINDOW = 50       # Increased for Trend Filter
        self.RSI_PERIOD = 14
        self.BB_PERIOD = 20
        self.BB_STD = 2.0
        self.MAX_POSITIONS = 5
        self.BASE_RISK_PCT = 0.15       # 15% equity per trade
        
        # --- Data Structures ---
        self.history = {}               # {symbol: deque(maxlen=50)}
        self.prev_prices = {}           # For "Tick Up" check

    def get_indicators(self, prices):
        """Calculates SMA, Bollinger Bands, and RSI."""
        if len(prices) < self.LOOKBACK_WINDOW:
            return None
            
        current_price = prices[-1]
        
        # 1. Bollinger Bands (20, 2)
        bb_slice = list(prices)[-self.BB_PERIOD:]
        sma_20 = statistics.mean(bb_slice)
        std_dev = statistics.stdev(bb_slice)
        upper_band = sma_20 + (self.BB_STD * std_dev)
        lower_band = sma_20 - (self.BB_STD * std_dev)
        
        # 2. RSI (14)
        gains = []
        losses = []
        # Calculate changes for the last 14 periods
        rsi_slice = list(prices)[-(self.RSI_PERIOD + 1):]
        for i in range(1, len(rsi_slice)):
            change = rsi_slice[i] - rsi_slice[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        # 3. Trend Filter (SMA 50)
        sma_50 = statistics.mean(prices) # Since maxlen=50
        
        return {
            'sma_20': sma_20,
            'sma_50': sma_50,
            'upper': upper_band,
            'lower': lower_band,
            'std_dev': std_dev,
            'rsi': rsi
        }

    def next(self, tick):
        """
        Main execution loop.
        tick: dict {symbol: price, ...}
        """
        # 1. Update Data
        for symbol, price in tick.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.LOOKBACK_WINDOW)
            self.history[symbol].append(price)

        # 2. Manage Existing Positions (Risk Management)
        # Iterate copy to allow deletion
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = tick.get(symbol)
            
            if not current_price: continue
            
            pos['ticks_held'] += 1
            entry_price = pos['entry']
            
            # Indicators for Exit
            inds = self.get_indicators(self.history[symbol])
            if not inds: continue

            # --- EXIT LOGIC ---
            
            # A. Dynamic Stop Loss (Hard Risk Control)
            if current_price <= pos['stop']:
                print(f"🛑 STOP LOSS: {symbol} @ {current_price:.2f}")
                self.close_position(symbol, current_price)
                continue

            # B. Mean Reversion Target (Take Profit)
            # Winner Wisdom: Don't be greedy, exit at the mean
            if current_price >= inds['sma_20']:
                print(f"💰 TAKE PROFIT (Mean Reverted): {symbol} @ {current_price:.2f}")
                self.close_position(symbol, current_price)
                continue
                
            # C. Time Decay (Mutation)
            # If trade is stale > 20 ticks and barely moving, cut it to free up capital
            if pos['ticks_held'] > 20 and current_price < entry_price:
                print(f"⌛ TIME DECAY EXIT: {symbol} (Stale)")
                self.close_position(symbol, current_price)
                continue

        # 3. Scan for New Entries
        if len(self.positions) >= self.MAX_POSITIONS:
            return

        for symbol, price in tick.items():
            if symbol in self.positions: continue
            if len(self.history[symbol]) < self.LOOKBACK_WINDOW: continue
            
            inds = self.get_indicators(self.history[symbol])
            prev_price = self.prev_prices.get(symbol, price)
            
            # --- ENTRY LOGIC (The Filter Stack) ---
            
            # 1. Statistical Anomaly (Bollinger Lower Band)
            is_cheap = price < inds['lower']
            
            # 2. Momentum Filter (RSI) - Inherited from Winner
            # Prevent catching falling knives in a crash
            is_oversold = inds['rsi'] < 30
            
            # 3. Trend Filter (Mutation)
            # Only buy dips if the long-term trend is UP (Price > SMA50)
            # OR if RSI is extremely oversold (< 20) implying a panic bounce
            is_uptrend = price > inds['sma_50']
            is_panic = inds['rsi'] < 20
            trend_confirmed = is_uptrend or is_panic
            
            # 4. Price Action Confirmation (Tick Up) - Inherited from Winner
            # Wait for the V-shape start
            tick_up = price > prev_price
            
            if is_cheap and is_oversold and trend_confirmed and tick_up:
                # --- DYNAMIC POSITION SIZING ---
                # High Volatility = Smaller Position
                volatility_ratio = inds['std_dev'] / price
                size_scalar = 1.0
                if volatility_ratio > 0.02: # High vol
                    size_scalar = 0.5
                
                # Dynamic Stop Loss: 2 StdDevs below entry
                stop_loss = price - (2.0 * inds['std_dev'])
                
                self.buy_position(symbol, price, size_scalar, stop_loss)

            # Update previous price for next tick
            self.prev_prices[symbol] = price

    def buy_position(self, symbol, price, scalar, stop_loss):
        """Executes buy and updates internal state."""
        amount_usd = (self.balance * self.BASE_RISK_PCT) * scalar
        if amount_usd < 10: return # Minimum trade size
        
        quantity = amount_usd / price
        self.positions[symbol] = {
            'entry': price,
            'size': quantity,
            'ticks_held': 0,
            'stop': stop_loss
        }
        self.balance -= amount_usd
        print(f"🚀 BUY: {symbol} @ {price:.2f} | RSI Confirmed | Stop: {stop_loss:.2f}")
        # SDK Hook: self.buy(symbol, quantity)

    def close_position(self, symbol, price):
        """Executes sell and updates internal state."""
        pos = self.positions[symbol]
        revenue = pos['size'] * price
        self.balance += revenue
        del self.positions[symbol]
        # SDK Hook: self.sell(symbol, pos['size'])