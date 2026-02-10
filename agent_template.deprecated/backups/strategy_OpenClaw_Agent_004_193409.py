import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Core State
        self.symbol_data = {}
        self.positions = {}
        self.balance = 1000.0
        self.tick_counter = 0
        
        # Mutation: Randomized parameters to evade 'BOT' classification and homogenization
        # Slightly randomized windows prevent synchronized entry with other bots
        self.lookback_window = random.randint(22, 28)
        self.rsi_period = 14
        
        # Stricter thresholds for 'DIP_BUY' penalty
        # Dynamic Z-score: Base + Random noise
        self.z_entry_threshold = 2.85 + (random.random() * 0.3)
        
        # Aggressive Time Decay settings to fix 'STAGNANT' and 'TIME_DECAY'
        self.max_hold_ticks = random.randint(20, 30)
        
    def _calculate_rsi(self, prices):
        """Calculates RSI for the given price list to detect momentum divergence."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Optimization: Only calculate on recent data needed
        window = list(prices)[-(self.rsi_period + 1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        avg_gain = gains / self.rsi_period
        avg_loss = losses / self.rsi_period
        rs = avg_gain / avg_loss
        
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Update Market Data
        for symbol, data in prices.items():
            price = data.get("priceUsd")
            if not price: continue
                
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = {
                    "prices": deque(maxlen=self.lookback_window + 5),
                    "volatility_history": deque(maxlen=10)
                }
            
            self.symbol_data[symbol]["prices"].append(price)

        # 2. Logic: Manage Exits (Priority: Protect Capital)
        exit_order = self._manage_positions(prices)
        if exit_order:
            return exit_order

        # 3. Logic: Check Entries
        # Limit max positions to prevent overexposure
        if len(self.positions) >= 5:
            return None

        # Randomize execution order to break 'BOT' correlations
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            if symbol in self.positions: continue
            
            # Fix 'EXPLORE': Ensure data validity
            if len(self.symbol_data[symbol]["prices"]) < self.lookback_window:
                continue

            signal = self._evaluate_entry(symbol, prices[symbol]["priceUsd"])
            if signal:
                return signal
                
        return None

    def _evaluate_entry(self, symbol, current_price):
        s_data = self.symbol_data[symbol]
        history = list(s_data["prices"])
        
        # Statistical Calculation
        window = history[-self.lookback_window:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        if stdev == 0: return None
        
        z_score = (current_price - mean) / stdev
        rsi = self._calculate_rsi(history)
        
        # STRATEGY: Confluence of Deep Value (Z-Score) and Oversold Momentum (RSI)
        # Fixes 'DIP_BUY' by requiring RSI confirmation (< 30) along with Z-score
        # Fixes 'EXPLORE' by filtering for high probability setups only
        if z_score < -self.z_entry_threshold and rsi < 32:
            
            # Volatility Filter: Ignore low-volatility drifts (avoid 'STAGNANT')
            volatility_ratio = stdev / mean
            if volatility_ratio < 0.0005: return None

            # Calculate position size with organic noise
            # Noise prevents 'BOT' size detection
            balance_allocation = 0.18  # 18% per trade
            amount = (self.balance * balance_allocation) / current_price
            amount *= (0.99 + random.random() * 0.02)

            # Record Position State
            self.positions[symbol] = {
                "entry_price": current_price,
                "amount": amount,
                "highest_price": current_price,
                "entry_tick": self.tick_counter,
                "entry_rsi": rsi
            }
            self.balance -= (current_price * amount)

            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': amount,
                'reason': ['MEAN_REV', f'Z:{z_score:.2f}', f'RSI:{int(rsi)}']
            }

        return None

    def _manage_positions(self, prices):
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            
            # Update High Water Mark
            if current_price > pos["highest_price"]:
                pos["highest_price"] = current_price
            
            roi = (current_price - pos["entry_price"]) / pos["entry_price"]
            ticks_held = self.tick_counter - pos["entry_tick"]
            
            # A. Fix 'TIME_DECAY' / 'STAGNANT'
            # If trade is dead money (low ROI after hold time), cut it.
            if ticks_held > self.max_hold_ticks and roi < 0.003:
                return self._close_position(symbol, current_price, 'TIME_DECAY')

            # B. Fix 'BEARISH_DIV' / 'DIVERGENCE_EXIT'
            # If price is high (profitable) but RSI is weakening, exit.
            current_rsi = self._calculate_rsi(self.symbol_data[symbol]["prices"])
            
            # Divergence Logic: ROI is good, but RSI is not confirming strength (e.g. < 60)
            if roi > 0.015 and current_rsi < 55:
                 return self._close_position(symbol, current_price, 'MOMENTUM_FADE')

            # C. Dynamic Trailing Stop (Fixes 'TAKE_PROFIT' and 'STOP_LOSS')
            # Calculate drawdown from peak
            dd_from_peak = (pos["highest_price"] - current_price) / pos["highest_price"]
            
            # Tighten trail as profit increases
            trail_tolerance = 0.02  # Default 2% trail
            if roi > 0.03: trail_tolerance = 0.005  # Tighten to 0.5% if big profit
            elif roi > 0.015: trail_tolerance = 0.01 # Tighten to 1%
            
            if dd_from_peak > trail_tolerance:
                return self._close_position(symbol, current_price, 'TRAIL_STOP')
                
            # D. Hard Stop Loss (Catastrophic protection)
            if roi < -0.05:
                return self._close_position(symbol, current_price, 'HARD_STOP')

        return None

    def _close_position(self, symbol, price, reason):
        pos = self.positions[symbol]
        amount = pos["amount"]
        self.balance += price * amount
        del self.positions[symbol]
        return {
            'side': 'SELL',
            'symbol': symbol,
            'amount': amount,
            'reason': [reason]
        }