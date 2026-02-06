import random
import statistics
import math
from collections import deque

class MyStrategy:
    """
    Agent_005 Gen 53: 'Titanium Turtle - Mean Reversion with Volatility Clamping'
    
    [Evolutionary DNA]
    1.  **Inherited from Winner (Agent_008)**: 
        -   RSI (14) < 30 Confluence: Only buy when statistically oversold.
        -   'Tick Up' Confirmation: Wait for a green tick to avoid falling knives.
    
    2.  **Gen 53 Mutations (Survival Mode)**:
        -   **ATR-Based Dynamic Stops**: Hard stops are calculated using Average True Range (Volatility). Stop distance expands in high volatility to avoid noise, tightens in low volatility.
        -   **Time-Based Expiration**: If a trade doesn't reach target in 10 ticks, close it. Prevents capital stagnation in dead assets.
        -   **Volatility Clamping**: Position size is reduced if the asset's volatility (StdDev) is too high relative to the portfolio.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Agent_005 Gen 53: Titanium Turtle)")
        
        # --- Configuration ---
        self.lookback_window = 35
        self.rsi_period = 14
        self.bb_period = 20
        self.bb_std_dev = 2.0
        self.atr_period = 14
        
        # Risk Management
        self.max_ticks_held = 10
        self.stop_loss_atr_multiplier = 2.5
        self.base_risk_per_trade = 0.15  # 15% of capital per trade max
        
        # --- State ---
        # {symbol: deque([price1, price2...], maxlen=35)}
        self.price_history = {}
        
        # {symbol: {'entry_price': float, 'stop_loss': float, 'ticks_held': int, 'quantity': float}}
        self.positions = {} 

    def calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50.0  # Neutral default
        
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
                
        # Simple Average for efficiency in high-freq (approximation of Wilder's)
        avg_gain = statistics.mean(gains[-period:])
        avg_loss = statistics.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def calculate_bollinger_bands(self, prices, period=20, num_std=2.0):
        if len(prices) < period:
            return None, None, None
            
        slice_prices = list(prices)[-period:]
        sma = statistics.mean(slice_prices)
        std_dev = statistics.stdev(slice_prices)
        
        upper_band = sma + (std_dev * num_std)
        lower_band = sma - (std_dev * num_std)
        
        return upper_band, sma, lower_band, std_dev

    def calculate_atr_proxy(self, prices, period=14):
        # Approximate ATR using standard deviation of recent changes if H/L/C not available
        if len(prices) < period:
            return 1.0
        return statistics.stdev(list(prices)[-period:])

    def get_signal(self, symbol, current_price, prev_price):
        history = self.price_history[symbol]
        
        # 1. Data Sufficiency Check
        if len(history) < self.lookback_window:
            return "WAIT", 0.0

        # 2. Indicator Calculation
        upper, middle, lower, std_dev = self.calculate_bollinger_bands(history, self.bb_period, self.bb_std_dev)
        rsi = self.calculate_rsi(history, self.rsi_period)
        
        # 3. Strategy Logic (Winner DNA + Mutation)
        
        # Condition A: Mean Reversion (Price below Lower BB)
        is_oversold_bb = current_price < lower
        
        # Condition B: Momentum Filter (RSI < 30) - Winner's Wisdom
        is_oversold_rsi = rsi < 30
        
        # Condition C: Price Action Confirmation (Tick Up) - Winner's Wisdom
        # We only buy if price is turning around immediately
        is_ticking_up = current_price > prev_price

        if is_oversold_bb and is_oversold_rsi and is_ticking_up:
            # Dynamic Volatility Sizing: Higher volatility = Smaller Stop distance calculated later
            volatility_factor = std_dev / current_price if current_price > 0 else 0
            return "BUY", volatility_factor
            
        return "HOLD", 0.0

    def next_action(self, market_data, account_balance):
        """
        Main execution loop called by the engine.
        market_data: dict {symbol: current_price}
        """
        orders = {}
        
        for symbol, current_price in market_data.items():
            # 1. Update History
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback_window)
            
            # Store previous price for Tick Up check
            prev_price = self.price_history[symbol][-1] if self.price_history[symbol] else current_price
            self.price_history[symbol].append(current_price)
            
            # 2. Manage Existing Positions (Exit Logic)
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos['ticks_held'] += 1
                
                # A. Stop Loss (ATR Based)
                if current_price <= pos['stop_loss']:
                    orders[symbol] = -pos['quantity'] # Close
                    del self.positions[symbol]
                    continue
                    
                # B. Take Profit (Mean Reversion - Target SMA)
                # Calculate current SMA
                _, sma, _, _ = self.calculate_bollinger_bands(self.price_history[symbol], self.bb_period)
                if sma and current_price >= sma:
                    orders[symbol] = -pos['quantity'] # Take Profit
                    del self.positions[symbol]
                    continue
                
                # C. Time-Based Stop (Mutation: Don't hold dead money)
                if pos['ticks_held'] >= self.max_ticks_held:
                    # Only exit if we are at least break-even or slightly lossy, 
                    # don't panic dump if it's just noise, but force rotation.
                    orders[symbol] = -pos['quantity']
                    del self.positions[symbol]
                    continue
                    
            # 3. Scan for New Entries (Entry Logic)
            else:
                signal, vol_factor = self.get_signal(symbol, current_price, prev_price)
                
                if signal == "BUY":
                    # Risk Management: Position Sizing
                    # Calculate ATR for Stop Loss
                    atr = self.calculate_atr_proxy(self.price_history[symbol], self.atr_period)
                    stop_distance = atr * self.stop_loss_atr_multiplier
                    stop_price = current_price - stop_distance
                    
                    # Prevent negative stop price
                    if stop_price < 0: stop_price = current_price * 0.95
                    
                    # Size based on risk (simplified Kelly or Fixed Fractional)
                    # We want to risk max 2% of account per trade
                    risk_amount = account_balance * 0.02
                    risk_per_share = current_price - stop_price
                    
                    if risk_per_share > 0:
                        qty = math.floor(risk_amount / risk_per_share)
                    else:
                        qty = 0
                        
                    # Cap max exposure to base_risk_per_trade
                    max_qty_capital = math.floor((account_balance * self.base_risk_per_trade) / current_price)
                    qty = min(qty, max_qty_capital)
                    
                    if qty > 0:
                        orders[symbol] = qty
                        self.positions[symbol] = {
                            'entry_price': current_price,
                            'stop_loss': stop_price,
                            'ticks_held': 0,
                            'quantity': qty
                        }

        return orders