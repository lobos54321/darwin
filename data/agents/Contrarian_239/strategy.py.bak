import random
import statistics
import math
from collections import deque

class MyStrategy:
    """
    Agent: Contrarian_239 -> Evolved: Adaptive_Regime_Phoenix_v3
    
    🧬 Evolution Report:
    1.  **Inherited Winner DNA (Phoenix)**: 
        - Retained RSI (14) & Bollinger Band logic.
        - Retained 'Tick Up' confirmation to avoid catching falling knives.
    
    2.  **CRITICAL FIX - Regime Filtering (The "Trend" Mutation)**:
        - Previous failure analysis: Bought dips during strong downtrends.
        - New Logic: Calculates a 50-period SMA to determine Market Regime.
        - Bull Regime (Price > SMA50): Buy aggressive dips (RSI < 40).
        - Bear Regime (Price < SMA50): ONLY buy extreme crashes (RSI < 25).
    
    3.  **Risk Management - Trailing Stop & Volatility Damping**:
        - Replaced hard stop with a Trailing Stop to let winners run but cut reversals.
        - Position sizing is now strictly limited to preserve the remaining $536 capital.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Adaptive_Regime_Phoenix_v3)")
        
        # Data storage
        self.history = {}       # {symbol: deque(maxlen=50)}
        self.positions = {}     # {symbol: {'entry_price': float, 'highest_price': float, 'shares': int}}
        
        # Parameters
        self.lookback = 20      # BB Period
        self.rsi_period = 14
        self.trend_period = 50  # Regime filter
        
        # Risk Params
        self.base_risk_per_trade = 0.10  # Risk 10% of equity per trade
        self.trailing_stop_pct = 0.03    # 3% Trailing Stop
        self.min_volatility = 0.005      # Avoid dead assets

    def get_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50  # Neutral
        
        gains = []
        losses = []
        for i in range(1, period + 1):
            change = prices[-i] - prices[-(i+1)]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def next(self, context):
        # 1. Update Context & Data
        current_prices = context['prices'] # Assuming dictionary {symbol: price}
        portfolio = context['portfolio']   # {symbol: quantity}
        cash = context['cash']
        orders = []

        for symbol, price in current_prices.items():
            # Initialize history
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.trend_period + 1)
            self.history[symbol].append(price)

            # Skip if not enough data
            if len(self.history[symbol]) < self.trend_period:
                continue

            prices = list(self.history[symbol])
            
            # --- Indicator Calculation ---
            # 1. Bollinger Bands (20)
            recent_prices = prices[-self.lookback:]
            sma20 = statistics.mean(recent_prices)
            std20 = statistics.stdev(recent_prices) if len(recent_prices) > 1 else 0
            if std20 == 0: continue # Skip flat assets
            
            upper_bb = sma20 + (2 * std20)
            lower_bb = sma20 - (2 * std20)
            
            # 2. RSI (14)
            rsi = self.get_rsi(prices, self.rsi_period)
            
            # 3. Regime Filter (SMA 50)
            sma50 = statistics.mean(prices[-self.trend_period:])
            is_bull_market = price > sma50
            
            # --- Position Management (Exit Logic) ---
            current_qty = portfolio.get(symbol, 0)
            
            if current_qty > 0:
                # Update Trailing Stop Logic
                if symbol not in self.positions:
                    self.positions[symbol] = {'entry_price': price, 'highest_price': price}
                
                # Update highest price observed since entry
                if price > self.positions[symbol]['highest_price']:
                    self.positions[symbol]['highest_price'] = price
                
                highest = self.positions[symbol]['highest_price']
                entry = self.positions[symbol]['entry_price']
                
                # Calculate dynamic stop price
                stop_price = highest * (1 - self.trailing_stop_pct)
                
                # EXIT 1: Trailing Stop Hit
                if price < stop_price:
                    orders.append({'symbol': symbol, 'action': 'SELL', 'quantity': current_qty, 'reason': 'TRAILING_STOP'})
                    del self.positions[symbol]
                    continue
                
                # EXIT 2: RSI Overbought (Take Profit)
                # Stronger take profit in bear markets
                exit_rsi = 75 if is_bull_market else 65
                if rsi > exit_rsi:
                    orders.append({'symbol': symbol, 'action': 'SELL', 'quantity': current_qty, 'reason': 'RSI_PEAK'})
                    del self.positions[symbol]
                    continue

            # --- Entry Logic ---
            elif current_qty == 0 and cash > 10:
                # Price Action Confirmation: Current > Prev (Tick Up)
                tick_up = prices[-1] > prices[-2]
                
                # Dynamic Thresholds based on Regime
                if is_bull_market:
                    # Aggressive: Buy standard dips
                    buy_signal = (price < lower_bb) and (rsi < 40) and tick_up
                    tag = 'BULL_DIP'
                else:
                    # Defensive: Only buy extreme fear
                    # Price must be significantly below Lower BB
                    buy_signal = (price < lower_bb - (0.5 * std20)) and (rsi < 25) and tick_up
                    tag = 'BEAR_CRASH'

                if buy_signal:
                    # Volatility Sizing: Lower size for higher volatility assets
                    volatility_ratio = std20 / price
                    risk_scalar = 0.02 / max(volatility_ratio, 0.01) # Target 2% volatility impact
                    risk_scalar = min(max(risk_scalar, 0.5), 1.5) # Clamp between 0.5x and 1.5x
                    
                    # Calculate quantity
                    allocation = cash * self.base_risk_per_trade * risk_scalar
                    quantity = int(allocation / price)
                    
                    if quantity > 0:
                        orders.append({'symbol': symbol, 'action': 'BUY', 'quantity': quantity, 'tag': tag})
                        self.positions[symbol] = {'entry_price': price, 'highest_price': price}

        return orders