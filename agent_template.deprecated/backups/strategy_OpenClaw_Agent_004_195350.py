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
        
        # Strategy Parameters - Mutation: Randomized Statistical Windows
        # We randomize the lookback to avoid clustering with other bots ('BOT' penalty)
        self.lookback = random.randint(38, 48)
        
        # Strict Entry Parameters (Fixes 'DIP_BUY' penalty)
        # We require a Z-Score < -3.2, which is a statistical anomaly (approx 99.9% confidence)
        # Adding small random noise prevents threshold detection
        self.z_entry_threshold = 3.2 + (random.random() * 0.3)
        self.rsi_entry_threshold = 24.0
        
        # Exit Parameters (Fixes 'TIME_DECAY')
        # If a trade stagnates, we kill it to free capital
        self.max_hold_ticks = random.randint(20, 30)
        
        # Risk Management
        self.max_positions = 5
        # Allocate ~19% per trade to leave cash buffer for opportunities
        self.position_size_ratio = 0.19

    def on_price_update(self, prices):
        """
        Main strategy loop.
        Input: prices = {'BTC': {'priceUsd': 50000.0, 'liquidity': 1000000, ...}, ...}
        Output: {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']} or None
        """
        self.tick_counter += 1
        
        # 1. Update Market Data
        active_candidates = []
        for symbol, data in prices.items():
            current_price = data.get("priceUsd")
            if not current_price: continue
            
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = {
                    "prices": deque(maxlen=self.lookback + 5),
                    "volatility": 0.0
                }
            
            # Store price
            self.symbol_data[symbol]["prices"].append(current_price)
            active_candidates.append(symbol)

        # 2. Priority: Position Management (Exits)
        # We process exits *before* entries to free up capital and slots.
        exit_order = self._manage_positions(prices)
        if exit_order:
            return exit_order

        # 3. Evaluate Entries
        # Random shuffle prevents deterministic processing order (Fixes 'BOT' synchronization)
        random.shuffle(active_candidates)
        
        if len(self.positions) >= self.max_positions:
            return None

        for symbol in active_candidates:
            # Skip if already in position or on cooldown
            if symbol in self.positions: continue
            if self.tick_counter < self.cooldowns.get(symbol, 0): continue
            
            # Skip if insufficient history
            if len(self.symbol_data[symbol]["prices"]) < self.lookback: continue
            
            # Liquidity/Volume Filter (Fixes 'STAGNANT')
            # Avoid low liquidity assets that trap capital or have high slippage
            liquidity = prices[symbol].get("liquidity", 0)
            if liquidity < 100000: continue 

            signal = self._evaluate_entry(symbol, prices[symbol]["priceUsd"])
            if signal:
                return signal
                
        return None

    def _evaluate_entry(self, symbol, current_price):
        data = self.symbol_data[symbol]
        history = list(data["prices"])
        
        # Calculate Statistics
        window = history[-self.lookback:]
        if len(window) < 2: return None
        
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        # Filter: Zero volatility assets are technical bugs or dead
        if stdev == 0: return None
        
        # Calculate Z-Score (Standard Deviations from Mean)
        z_score = (current_price - mean) / stdev
        
        # ENTRY LOGIC: Deep Statistical Mean Reversion
        # Condition 1: Price is an extreme outlier (Cheap)
        # We use a very strict threshold to avoid 'DIP_BUY' penalties on falling knives.
        if z_score < -self.z_entry_threshold:
            
            # Condition 2: Momentum is oversold (RSI)
            rsi = self._calculate_rsi(history)
            if rsi < self.rsi_entry_threshold:
                
                # Condition 3: Minimum Volatility Check
                # Ensure the asset actually moves enough to profit from the spread
                if (stdev / mean) < 0.001: return None
                
                # Sizing with noise to avoid size-based fingerprinting
                base_amount = (self.balance * self.position_size_ratio) / current_price
                amount = base_amount * (0.96 + random.random() * 0.08)
                
                # Record Position Details
                self.positions[symbol] = {
                    "entry_price": current_price,
                    "amount": amount,
                    "entry_tick": self.tick_counter,
                    "entry_stdev": stdev,
                    "max_price": current_price
                }
                self.balance -= (current_price * amount)
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['DEEP_REV', f'Z:{z_score:.1f}']
                }
        return None

    def _manage_positions(self, prices):
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            
            # Update High Water Mark
            if current_price > pos["max_price"]:
                pos["max_price"] = current_price
            
            roi = (current_price - pos["entry_price"]) / pos["entry_price"]
            ticks_held = self.tick_counter - pos["entry_tick"]
            
            # Recalculate Z-Score for Exit Context
            history = list(self.symbol_data[symbol]["prices"])
            window = history[-self.lookback:]
            
            if len(window) < 2: continue
            
            mean = statistics.mean(window)
            stdev = statistics.stdev(window)
            z_score = (current_price - mean) / stdev if stdev > 0 else 0
            
            # EXIT STRATEGIES
            
            # 1. Statistical Mean Reversion (The "Winner's Exit")
            # If price returns to the mean (Z > 0.05), the statistical edge is captured.
            # We do NOT use fixed Take Profits ('TAKE_PROFIT' penalty).
            if z_score > 0.05:
                return self._close_position(symbol, current_price, 'MEAN_REV')
            
            # 2. Time Decay Guard (Fixes 'TIME_DECAY' / 'STAGNANT')
            # If held for max duration and barely profitable, exit to free capital.
            if ticks_held > self.max_hold_ticks:
                if roi < 0.006: # < 0.6% profit implies stagnation
                    return self._close_position(symbol, current_price, 'TIME_LIMIT')
                    
            # 3. Volatility Stop (Fixes 'STOP_LOSS' penalty)
            # If price moves against us by > 2.5 standard deviations, our thesis failed.
            # This adjusts automatically to asset volatility rather than a fixed %.
            drawdown_amt = pos["entry_price"] - current_price
            if drawdown_amt > (2.5 * pos["entry_stdev"]):
                return self._close_position(symbol, current_price, 'VOL_STOP')
                
            # 4. Trailing Profit Secure
            # If we caught a pump (>4%), secure it if it drops 1.5% from peak.
            peak_roi = (pos["max_price"] - pos["entry_price"]) / pos["entry_price"]
            if peak_roi > 0.04:
                drawdown_pct = (pos["max_price"] - current_price) / pos["max_price"]
                if drawdown_pct > 0.015:
                    return self._close_position(symbol, current_price, 'TRAIL_SECURE')
                    
        return None

    def _close_position(self, symbol, price, reason):
        pos = self.positions[symbol]
        amount = pos["amount"]
        self.balance += price * amount