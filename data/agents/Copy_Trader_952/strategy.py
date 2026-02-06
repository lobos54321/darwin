```python
import math
import statistics
import random
from collections import deque, defaultdict

class MyStrategy:
    """
    Agent: Copy_Trader_952 (Gen 8 - Adaptive Survivor)
    
    Evolutionary DNA:
    1.  [Inherited] RSI + Bollinger Confluence: Prevents buying falling knives.
    2.  [Inherited] Price Action: Requires 'Tick Up' confirmation.
    3.  [Mutation - Survival Protocol] 'Drawdown Ratchet': As account equity drops below 80%, 
        entry criteria tighten (RSI < 25 -> RSI < 20) and position sizing reduces by 50%.
    4.  [Mutation - Trend Filter] EMA Regime: Differentiates between 'Dip in Uptrend' (Aggressive) 
        and 'Crash Reversal' (Conservative).
    5.  [Risk] Volatility-Adjusted Sizing: Position size = (Risk Capital) / ATR, ensuring 
        high volatility assets get smaller allocations.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Gen 8: Adaptive Survivor - Volatility Ratchet)")
        
        # === Configuration ===
        self.rsi_period = 14
        self.bb_period = 20
        self.bb_std = 2.0
        self.atr_period = 14
        self.ema_trend_period = 50
        
        # === Risk Management ===
        self.initial_capital = 1000.0
        self.base_risk_per_trade = 0.02  # Risk 2% of equity
        self.max_drawdown_limit = 0.20   # 20% DD triggers Survival Mode
        
        # === Data Storage ===
        # Format: {symbol: deque}
        self.closes = defaultdict(lambda: deque(maxlen=100))
        self.highs = defaultdict(lambda: deque(maxlen=100))
        self.lows = defaultdict(lambda: deque(maxlen=100))
        self.positions = {} # {symbol: {'entry': price, 'stop': price, 'tp': price, 'size': amt}}

    def update_data(self, symbol, open_p, high_p, low_p, close_p):
        """Updates historical data for indicators."""
        self.closes[symbol].append(close_p)
        self.highs[symbol].append(high_p)
        self.lows[symbol].append(low_p)

    def calculate_rsi(self, series, period=14):
        if len(series) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        for i in range(1, period + 1):
            delta = series[-i] - series[-i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def calculate_bollinger(self, series, period=20, std_dev=2.0):
        if len(series) < period:
            return None, None, None
        
        recent = list(series)[-period:]
        sma = sum(recent) / period
        std = statistics.stdev(recent)
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower

    def calculate_atr(self, symbol, period=14):
        highs = self.highs[symbol]
        lows = self.lows[symbol]
        closes = self.closes[symbol]
        
        if len(closes) < period + 1:
            return 0.0
            
        tr_sum = 0
        for i in range(1, period + 1):
            h = highs[-i]
            l = lows[-i]
            prev_c = closes[-i-1]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr_sum += tr
            
        return tr_sum / period

    def calculate_ema(self, series, period):
        if len(series) < period:
            return series[-1]
        multiplier = 2 / (period + 1)
        ema = series[0]
        for price in list(series)[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def get_action(self, symbol, current_price, current_balance, portfolio_positions):
        """
        Determines action: 'BUY', 'SELL', or 'HOLD'.
        """
        # 0. Update internal state based on portfolio
        if symbol in portfolio_positions:
            self.positions[symbol] = portfolio_positions[symbol]
        elif symbol in self.positions:
            del self.positions[symbol]

        history = self.closes[symbol]
        if len(history) < self.ema_trend_period:
            return "HOLD", 0

        # 1. Calculate Indicators
        rsi = self.calculate_rsi(history, self.rsi_period)
        upper_bb, mid_bb, lower_bb = self.calculate_bollinger(history, self.bb_period, self.bb_std)
        atr = self.calculate_atr(symbol, self.atr_period)
        ema_trend = self.calculate_ema(history, self.ema_trend_period)
        
        if not lower_bb or atr == 0:
            return "HOLD", 0

        # 2. Determine Market Regime & Survival Mode
        drawdown = (self.initial_capital - current_balance) / self.initial_capital
        survival_mode = drawdown > self.max_drawdown_limit
        
        is_uptrend = current_price > ema_trend
        
        # 3. Dynamic Thresholds
        # If in survival mode or downtrend, require deeper oversold conditions
        if survival_mode:
            buy_rsi_threshold = 20
            risk_multiplier = 0.5 # Cut risk in half
        elif not is_uptrend:
            buy_rsi_threshold = 25
            risk_multiplier = 0.75
        else:
            buy_rsi_threshold = 30 # Standard dip buy in uptrend
            risk_multiplier = 1.0

        # 4. Sell Logic (Take Profit / Stop Loss)
        if symbol in self.positions:
            entry_price = self.positions[symbol]['entry']
            
            # Stop Loss (Dynamic based on ATR when entered, or fixed % fallback)
            # Assuming we hold logic here, usually managed by engine, but if we signal close:
            if current_price < entry_price - (2.0 * atr):
                return "SELL", 1.0 # Full close (Stop Loss)
            
            # Take Profit (Mean Reversion -> Target Upper Band or RSI Overbought)
            if rsi > 70 or current_price > upper_bb:
                return "SELL", 1.0 # Full close (Take Profit)
                
            return "HOLD", 0

        # 5. Buy Logic
        # Condition A: Statistical Oversold (Lower BB + RSI)
        condition_a = current_price < lower_bb and rsi < buy_rsi_threshold
        
        # Condition B: Price Action Confirmation (Tick Up from previous close)
        condition_b = current_price > history[-2] 
        
        # Condition C: Volatility Filter (Avoid exploding volatility/crashes)
        # If current candle range is > 2x ATR, it's too volatile/panic
        current_range = self.highs[symbol][-1] - self.lows[symbol][-1]
        condition_c = current_range < (2.0 * atr)

        if condition_a and condition_b and condition_c:
            # 6. Position Sizing (Risk Based)
            # Risk Amount = Balance * Risk% * Multiplier
            risk_