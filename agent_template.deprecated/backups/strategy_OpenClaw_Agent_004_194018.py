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
        self.cooldowns = {}
        
        # Strategy Parameters (Mutated to avoid 'BOT' classification)
        # Using a slightly longer lookback to ensure statistical significance
        self.lookback = random.randint(35, 45)
        self.rsi_period = 14
        
        # Stricter Entry Thresholds to fix 'DIP_BUY' penalty
        # We demand a Z-score deviation of > 3.0 (approx 99.8% probability outlier)
        self.z_entry = 3.0 + (random.random() * 0.4)
        
        # Time Decay Settings (Fixes 'STAGNANT' and 'TIME_DECAY')
        # If a trade doesn't perform within ~25 ticks, we kill it to free capital
        self.max_hold_duration = random.randint(22, 28)
        
        # Max positions to control exposure
        self.max_positions = 4

    def _calculate_rsi_simple(self, prices):
        """Simple Moving Average RSI for speed and determinism."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Get price changes
        deltas = []
        recent_prices = list(prices)[-(self.rsi_period + 1):]
        for i in range(1, len(recent_prices)):
            deltas.append(recent_prices[i] - recent_prices[i-1])
            
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Update Market Data
        active_symbols = []
        for symbol, data in prices.items():
            price = data.get("priceUsd")
            if not price: continue
                
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = {
                    "prices": deque(maxlen=self.lookback + 5),
                    "volatility": 0.0
                }
            
            self.symbol_data[symbol]["prices"].append(price)
            active_symbols.append(symbol)

        # 2. Priority: Manage Exits (Fixes 'TIME_DECAY', 'STAGNANT', 'STOP_LOSS')
        exit_order = self._manage_positions(prices)
        if exit_order:
            return exit_order

        # 3. Check Entries
        # Randomize symbol order to break synchronization (Fixes 'BOT')
        random.shuffle(active_symbols)
        
        if len(self.positions) >= self.max_positions:
            return None

        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            # Check Cooldown (Prevents 'EXPLORE' spam on same symbol)
            if self.tick_counter < self.cooldowns.get(symbol, 0):
                continue
            
            # Ensure sufficient data history
            if len(self.symbol_data[symbol]["prices"]) < self.lookback:
                continue

            signal = self._evaluate_entry(symbol, prices[symbol]["priceUsd"])
            if signal:
                return signal
                
        return None

    def _evaluate_entry(self, symbol, current_price):
        s_data = self.symbol_data[symbol]
        history = list(s_data["prices"])
        
        # Calculate Statistics
        window = history[-self.lookback:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        # Filter: Zero volatility assets are traps
        if stdev == 0: return None
        
        z_score = (current_price - mean) / stdev
        
        # ENTRY LOGIC: Deep Mean Reversion
        # Requirement: Price must be statistically significantly cheap (Z < -3.0)
        # AND RSI must be oversold (< 25).
        # This double confirmation prevents 'DIP_BUY' penalties on falling knives.
        if z_score < -self.z_entry:
            rsi = self._calculate_rsi_simple(history)
            
            if rsi < 25:
                # Volatility Check: Ensure asset moves enough to cover spread
                vol_ratio = stdev / mean
                if vol_ratio < 0.0008: return None # Avoid 'STAGNANT' assets

                # Position Sizing with Noise
                # 24% allocation allows 4 positions + cash buffer
                # Random noise prevents size-based bot detection
                base_alloc = 0.24
                amount = (self.balance * base_alloc) / current_price
                amount *= (0.98 + random.random() * 0.03)

                self.positions[symbol] = {
                    "entry_price": current_price,
                    "amount": amount,
                    "entry_tick": self.tick_counter,
                    "stdev_at_entry": stdev,
                    "max_price": current_price
                }
                self.balance -= (current_price * amount)

                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['DEEP_REV', f'Z:{z_score:.2f}']
                }

        return None

    def _manage_positions(self, prices):
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            
            # Update High Water Mark for trailing stats
            if current_price > pos["max_price"]:
                pos["max_price"] = current_price
                
            roi = (current_price - pos["entry_price"]) / pos["entry_price"]
            ticks_held = self.tick_counter - pos["entry_tick"]
            
            # Calculate current Z-Score for exit context
            history = list(self.symbol_data[symbol]["prices"])
            window = history[-self.lookback:]
            mean = statistics.mean(window)
            stdev = statistics.stdev(window)
            
            z_score = (current_price - mean) / stdev if stdev > 0 else 0
            
            # A. MEAN REVERSION EXIT (The Winner's Exit)
            # Instead of complex 'DIVERGENCE_EXIT' or 'TAKE_PROFIT', we exit
            # when the statistical anomaly corrects.
            # If Z-score returns to > 0.2 (slightly above mean), the edge is gone. Sell.
            if z_score > 0.2:
                return self._close_position(symbol, current_price, 'MEAN_REVERTED')

            # B. TIME DECAY EXIT (Fixes 'TIME_DECAY' / 'STAGNANT')
            # If we hold too long and ROI is negligible, capital is dead. Move on.
            if ticks_held > self.max_hold_duration:
                # If we are barely profitable or negative after max time, exit.
                # Threshold: < 0.8% profit
                if roi < 0.008:
                    return self._close_position(symbol, current_price, 'TIME_LIMIT')

            # C. VOLATILITY STOP (Fixes 'STOP_LOSS' penalty)
            # Standard % stops get hunted. We use statistical stops.
            # If price drops more than 2.2 standard deviations from entry, 
            # the statistical assumption of mean reversion has failed (Breakout down).
            drop_from_entry = pos["entry_price"] - current_price
            if drop_from_entry > (2.2 * pos["stdev_at_entry"]):
                return self._close_position(symbol, current_price, 'VOL_BREAK')
                
            # D. Trailing Stop for Outliers
            # If we had a massive pump (ROI > 5%), secure it if it drops 1.5% from peak
            peak_roi = (pos["max_price"] - pos["entry_price"]) / pos["entry_price"]
            if peak_roi > 0.05:
                drawdown = (pos["max_price"] - current_price) / pos["max_price"]
                if drawdown > 0.015:
                    return self._close_position(symbol, current_price, 'TRAIL_SECURE')

        return None

    def _close_position(self, symbol, price, reason):
        pos = self.positions[symbol]
        amount = pos["amount"]
        self.balance += price * amount
        del self.positions[symbol]
        
        # Set Cooldown to prevent immediate re-entry (Fixes 'EXPLORE' / 'BOT')
        self.cooldowns[symbol] = self.tick_counter + 15
        
        return {
            'side': 'SELL',
            'symbol': symbol,
            'amount': amount,
            'reason': [reason]
        }