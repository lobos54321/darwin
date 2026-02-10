import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.symbol_data = {}
        self.balance = 1000.0
        self.positions = {}
        
        # Mutation: Genetic parameters to prevent homogenization
        # Unique lookback periods and thresholds per instance
        self.vol_lookback = random.randint(15, 25)
        self.z_score_window = random.randint(18, 26)
        self.rsi_period = random.randint(6, 12)
        
        # Risk settings
        self.max_positions = 5
        self.base_risk_pct = 0.02
        self.max_drawdown_tolerance = 0.04
        
        # Trailing stop parameters (ATR based)
        self.atr_stop_mult = 2.5 + (random.random() * 0.5)
        self.profit_target_atr = 4.0
        
        # Banned tags logic (simple set, not actively used but kept for structure)
        self.banned_tags = set()

    def on_price_update(self, prices):
        """
        Input: dict of {symbol: {'priceUsd': float, ...}}
        Output: dict {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']} or None
        """
        # 1. Update Data & Indicators
        for symbol, data in prices.items():
            price = data.get("priceUsd")
            if not price: 
                continue
                
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = {
                    "prices": deque(maxlen=60),
                    "entry_price": 0.0,
                    "highest_price": 0.0,
                    "volatility": 0.0
                }
            
            s_data = self.symbol_data[symbol]
            s_data["prices"].append(price)
            
            # Update position tracking
            if symbol in self.positions:
                s_data["highest_price"] = max(s_data["highest_price"], price)

        # 2. Manage Exits (Priority)
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order

        # 3. Check Entries
        # Shuffle symbols to avoid alphabetical bias in execution
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        if len(self.positions) >= self.max_positions:
            return None

        for symbol in symbols:
            if symbol in self.positions:
                continue
                
            signal = self._analyze_symbol(symbol)
            if signal:
                return signal
                
        return None

    def _analyze_symbol(self, symbol):
        data = self.symbol_data[symbol]
        history = list(data["prices"])
        
        # Require minimum history
        if len(history) < self.z_score_window + 2:
            return None
            
        current_price = history[-1]
        
        # --- Indicators ---
        # 1. Z-Score (Statistical Deviation)
        # Replacing simple RSI/Stoch logic with statistical variance
        sma = statistics.mean(history[-self.z_score_window:])
        stdev = statistics.stdev(history[-self.z_score_window:])
        if stdev == 0: return None
        z_score = (current_price - sma) / stdev
        
        # 2. ATR (Volatility)
        atr = self._calculate_atr(history, period=10)
        
        # 3. RSI (Momentum)
        rsi = self._calculate_rsi(history, self.rsi_period)
        
        # --- Strategy Logic ---
        
        # STRATEGY A: Statistical Mean Reversion (Sniper)
        # Instead of generic 'DIP_BUY', we use strict statistical deviation
        # Condition: Price is > 2.5 std devs below mean AND RSI is oversold
        if z_score < -2.5 and rsi < 25:
            # Mutation: Volatility-adjusted sizing
            # Lower position size if volatility is extreme to prevent ruin
            vol_factor = 1.0 if atr < (current_price * 0.01) else 0.6
            
            amount = self._calculate_position_size(current_price, vol_factor)
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': amount,
                'reason': ['STAT_REVERSION', f'Z:{z_score:.1f}']
            }

        # STRATEGY B: Volatility Breakout (Expansion)
        # Instead of 'TREND_FOLLOW', we catch the explosive move out of consolidation
        # Condition: Price breaks upper band (SMA + 2std) AND Volatility is expanding
        upper_band = sma + (2.0 * stdev)
        
        # Detect volatility expansion: Current ATR > Average ATR of recent past
        recent_atrs = [] 
        # approximate ATR history roughly
        if len(history) > 20:
             # Look at volatility change
             prev_vol = statistics.stdev(history[-20:-10])
             curr_vol = stdev
             vol_expanding = curr_vol > (prev_vol * 1.2)
        else:
             vol_expanding = False

        if current_price > upper_band and vol_expanding and rsi > 55 and rsi < 80:
            # Don't buy if RSI is already peaked (>80)
            amount = self._calculate_position_size(current_price, 0.8) # 0.8 scale for breakouts
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': amount,
                'reason': ['VOL_EXPANSION', 'BREAKOUT']
            }
            
        return None

    def _check_exits(self, prices):
        """
        Manages exits using dynamic Chandelier Exits (ATR Trailing Stop).
        Avoids fixed % exits which are brittle.
        """
        for symbol, amount in list(self.positions.items()):
            price = prices[symbol]["priceUsd"]
            data = self.symbol_data[symbol]
            
            entry = data["entry_price"]
            highest = data["highest_price"]
            
            history = list(data["prices"])
            if len(history) < 10: continue
            
            atr = self._calculate_atr(history, period=10)
            
            # Dynamic Stop Loss: Highest Price - (Multiplier * ATR)
            # This tightens as price moves up (Trailing)
            stop_price = highest - (atr * self.atr_stop_mult)
            
            # Take Profit: Target based on volatility (e.g., 4 ATRs)
            tp_price = entry + (atr * self.profit_target_atr)
            
            # Logic:
            # 1. Hit Trailing Stop
            if price < stop_price:
                self._close_position(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['ATR_TRAIL_STOP']
                }
            
            # 2. Hit Volatility Target
            if price > tp_price:
                self._close_position(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['VOL_TARGET_HIT']
                }

            # 3. Emergency/Sanity Stop (Hard % limit)
            pct_change = (price - entry) / entry
            if pct_change < -self.max_drawdown_tolerance:
                self._close_position(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['HARD_STOP_LOSS']
                }
                
        return None

    def _calculate_position_size(self, price, multiplier=1.0):
        # Inverse sizing: Higher risk/volatility should equate to smaller size?
        # Simplified here: Fixed % of balance * multiplier
        trade_val = self.balance * self.base_risk_pct * multiplier
        # Ensure we don't trade tiny dust
        if trade_val < 5.0: trade_val = 10.0
        
        amount = trade_val / price
        # Record expected position (simulated fill)
        return round(amount, 6)

    def _close_position(self, symbol):
        if symbol in self.positions:
            del self.positions[symbol]
        if symbol in self.symbol_data:
            # Reset entry stats
            self.symbol_data[symbol]["entry_price"] = 0.0
            self.symbol_data[symbol]["highest_price"] = 0.0

    def on_trade_executed(self, symbol, side, amount, price):
        # Callback to confirm trade execution
        if side == 'BUY':
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
            self.symbol_data[symbol]["entry_price"] = price
            self.symbol_data[symbol]["highest_price"] = price
        elif side == 'SELL':
            # Cleaned up in _close_position usually, but safe fallback
            if symbol in self.positions:
                del self.positions[symbol]

    # --- Helpers ---

    def _calculate_rsi(self, prices, period):
        if len(prices) < period + 1:
            return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        if not gains: return 0.0
        if not losses: return 100.0
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0: return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_atr(self, prices, period=14):
        if len(prices) < period + 1:
            return prices[-1] * 0.01 # Default 1% if no history
            
        tr_sum = 0.0
        for i in range(1, min(len(prices), period + 1)):
            high = prices[-i] # Simplified TR: assuming high=close for tick data
            low = prices[-i]
            prev_close = prices[-(i+1)]
            # True Range approximation for tick data (Tick Volatility)
            # TR = |Current - Prev|
            tr = abs(high - prev_close) 
            tr_sum += tr
            
        return tr_sum / period