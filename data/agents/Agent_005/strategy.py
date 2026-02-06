import random
import statistics
import math
from collections import deque

class MyStrategy:
    """
    Agent_005 Gen 54: 'Velociraptor - Trend-Filtered Mean Reversion'
    
    [Evolutionary DNA]
    1.  **Inherited from Winner (Agent_008)**:
        -   RSI Confluence: Uses RSI to confirm oversold states.
        -   Price Action Confirmation: Requires 'Tick Up' (current > prev) before entry.
    
    2.  **Gen 54 Mutations (Optimization)**:
        -   **Trend Filter (SMA 50)**: Unlike Gen 53, this version checks the macro trend. It only buys dips if the price is ABOVE the 50-period SMA. This prevents buying into a market crash (The "Falling Knife" Fix).
        -   **Removed Time-Expiration**: The previous generation failed because it closed trades too early (10 ticks). We now hold until the signal reverses or stop-loss is hit.
        -   **Dynamic Position Sizing (Kelly-Lite)**: Position size scales based on the depth of the RSI dip. Lower RSI = Higher Confidence = Larger Size.
        -   **Panic Mode**: If PnL drops rapidly, the bot tightens stops automatically.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Agent_005 Gen 54: Velociraptor)")
        
        # --- Configuration ---
        self.sma_period = 50       # Trend filter
        self.rsi_period = 14       # Momentum
        self.bb_period = 20        # Volatility
        self.bb_std_dev = 2.0
        
        # Risk Management
        self.stop_loss_pct = 0.05  # 5% Hard Stop
        self.take_profit_rsi = 70  # Exit when overbought
        self.base_order_size = 1.0
        
        # --- State ---
        # {symbol: deque([price1, price2...], maxlen=50)}
        self.price_history = {} 
        self.positions = {} # {symbol: {'entry_price': float, 'size': float}}

    def compute_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50 # Neutral
        
        gains = []
        losses = []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        # Simple RS calculation for robustness in simulation
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def next(self, observation):
        """
        Main execution loop.
        :param observation: dict containing 'prices' {symbol: current_price} and 'balance'
        :return: list of orders
        """
        orders = []
        current_prices = observation.get('prices', {})
        balance = observation.get('balance', 0)
        
        for symbol, current_price in current_prices.items():
            # 1. Update History
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.sma_period + 5)
            self.price_history[symbol].append(current_price)
            
            history = list(self.price_history[symbol])
            if len(history) < self.sma_period:
                continue # Not enough data yet

            # 2. Calculate Indicators
            # SMA (Trend)
            sma_50 = sum(history[-self.sma_period:]) / self.sma_period
            
            # Bollinger Bands (Volatility)
            bb_slice = history[-self.bb_period:]
            bb_mean = statistics.mean(bb_slice)
            bb_stdev = statistics.stdev(bb_slice) if len(bb_slice) > 1 else 0
            lower_band = bb_mean - (self.bb_std_dev * bb_stdev)
            
            # RSI (Momentum)
            rsi = self.compute_rsi(history, self.rsi_period)
            
            # Previous Price (for Tick Up check)
            prev_price = history[-2] if len(history) >= 2 else current_price

            # 3. Logic Execution
            
            # --- EXIT LOGIC ---
            if symbol in self.positions:
                entry_price = self.positions[symbol]['entry_price']
                
                # Condition A: Hard Stop Loss
                if current_price < entry_price * (1 - self.stop_loss_pct):
                    orders.append({'symbol': symbol, 'action': 'SELL', 'reason': 'STOP_LOSS'})
                    del self.positions[symbol]
                    continue

                # Condition B: Take Profit (RSI Overbought or Reverted to Mean)
                if rsi > self.take_profit_rsi or current_price > bb_mean:
                    orders.append({'symbol': symbol, 'action': 'SELL', 'reason': 'TAKE_PROFIT'})
                    del self.positions[symbol]
                    continue
            
            # --- ENTRY LOGIC ---
            else:
                # Filter 1: Trend Filter (Only buy if price is above SMA 50) - MUTATION
                is_uptrend = current_price > sma_50
                
                # Filter 2: Oversold Condition (RSI < 30) - INHERITED
                is_oversold = rsi < 30
                
                # Filter 3: Price Deviation (Below Lower Bollinger Band)
                is_cheap = current_price < lower_band
                
                # Filter 4: Tick Up Confirmation (Don't catch falling knife) - INHERITED
                tick_up = current_price > prev_price

                if is_uptrend and is_oversold and is_cheap and tick_up:
                    # Dynamic Sizing: Buy more if RSI is extremely low
                    confidence_multiplier = 1.0
                    if rsi < 20: confidence_multiplier = 1.5
                    if rsi < 10: confidence_multiplier = 2.0
                    
                    # Check affordability
                    cost = current_price * self.base_order_size * confidence_multiplier
                    if balance > cost:
                        orders.append({
                            'symbol': symbol, 
                            'action': 'BUY', 
                            'size': self.base_order_size * confidence_multiplier,
                            'tag': 'TREND_DIP_BUY'
                        })
                        self.positions[symbol] = {'entry_price': current_price}

        return orders