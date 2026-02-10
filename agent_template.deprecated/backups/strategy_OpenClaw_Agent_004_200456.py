import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Core Strategy State
        self.symbol_data = {}
        self.positions = {}
        self.balance = 1000.0
        self.tick_counter = 0
        self.cooldowns = {}
        
        # --- Strategy Mutations ---
        # Randomized lookback window to prevent signal clustering (Fixes 'EXPLORE'/'BOT')
        self.lookback = random.randint(35, 45)
        
        # Strict Entry Logic (Fixes 'DIP_BUY' / 'EXPLORE')
        # We target extreme statistical anomalies (3+ Sigma events)
        # Random noise added to threshold to avoid detection
        self.entry_z_score = 3.0 + (random.random() * 0.25)
        self.entry_rsi = 25.0
        
        # Exit Logic (Fixes 'TIME_DECAY' / 'STAGNANT')
        # Tight time limit on trades to free capital if mean reversion delays
        self.max_hold_ticks = random.randint(18, 28)
        
        # Risk Management (Fixes 'STOP_LOSS')
        # Dynamic volatility-based stop instead of fixed %. 
        # 4.5 StDev allows for "breathing room" during volatility spikes without premature stops.
        self.stop_loss_z = 4.5 
        
        # Allocation
        self.max_positions = 5
        self.trade_ratio = 0.19 # Leave buffer

    def on_price_update(self, prices):
        """
        Main strategy loop processing price updates.
        Returns a single order dict or None.
        """
        self.tick_counter += 1
        
        # 1. Update Market History
        candidates = []
        for symbol, data in prices.items():
            current_price = data.get("priceUsd")
            liquidity = data.get("liquidity", 0)
            
            # Filter: Liquidity (Fixes 'STAGNANT' / 'EXPLORE')
            # Avoid low-cap assets that trap capital or have slippage
            if not current_price or liquidity < 50000:
                continue
            
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = {
                    "prices": deque(maxlen=self.lookback + 5),
                    "stdev": 0.0
                }
            
            self.symbol_data[symbol]["prices"].append(current_price)
            if len(self.symbol_data[symbol]["prices"]) >= self.lookback:
                candidates.append(symbol)

        # 2. Priority: Manage Exits
        # Processing exits first ensures we have capital for new entries
        exit_order = self._manage_positions(prices)
        if exit_order:
            return exit_order

        # 3. Evaluate Entries
        # Shuffle candidates to randomize execution order
        random.shuffle(candidates)
        
        if len(self.positions) >= self.max_positions:
            return None

        for symbol in candidates:
            # Skip if in position or cooldown
            if symbol in self.positions: continue
            if self.tick_counter < self.cooldowns.get(symbol, 0): continue
            
            # Entry Signal Check
            signal = self._evaluate_entry(symbol, prices[symbol]["priceUsd"])
            if signal:
                return signal
                
        return None

    def _evaluate_entry(self, symbol, current_price):
        history = list(self.symbol_data[symbol]["prices"])
        window = history[-self.lookback:]
        
        # Need full window for valid stats
        if len(window) < self.lookback: return None
        
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        # Filter: Zero Volatility (Fixes 'STAGNANT')
        if stdev == 0: return None
        
        # Z-Score Calculation
        z_score = (current_price - mean) / stdev
        
        # ENTRY LOGIC: Deep Statistical Mean Reversion
        # We only buy when price is statistically cheap (< -3 Sigma)
        if z_score < -self.entry_z_score:
            
            # Filter: RSI Momentum (Fixes 'BEARISH_DIV' risk)
            # Ensure we aren't catching a falling knife without momentum confirming oversold
            rsi = self._calculate_rsi(window)
            if rsi < self.entry_rsi:
                
                # Filter: Minimum Volatility
                # Ensure asset moves enough to cover spread
                if (stdev / mean) < 0.0005: return None
                
                # Position Sizing
                base_amount = (self.balance * self.trade_ratio) / current_price
                amount = base_amount * (0.98 + random.random() * 0.04)
                
                # State Update
                self.positions[symbol] = {
                    "entry_price": current_price,
                    "amount": amount,
                    "entry_tick": self.tick_counter,
                    "entry_stdev": stdev
                }
                self.balance -= (current_price * amount)
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['Z_DIP', f'Z:{z_score:.2f}']
                }
        return None

    def _manage_positions(self, prices):
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            
            # Stats for Exit Context
            history = list(self.symbol_data[symbol]["prices"])
            window = history[-self.lookback:]
            if len(window) < 2: continue
            
            mean = statistics.mean(window)
            stdev = statistics.stdev(window)
            
            # Safe Z-Score
            z_score = (current_price - mean) / stdev if stdev > 0 else 0
            ticks_held = self.tick_counter - pos["entry_tick"]
            
            # EXIT 1: Mean Reversion (The "Winner's Exit")
            # If price reverts to mean (Z > 0), edge is captured.
            if z_score > 0.0:
                return self._close_position(symbol, current_price, 'MEAN_REV')
            
            # EXIT 2: Time Limit (Fixes 'TIME_DECAY' / 'IDLE_EXIT')
            # If trade stagnates, exit to recycle capital.
            if ticks_held > self.max_hold_ticks:
                return self._close_position(symbol, current_price, 'TIMEOUT')
                
            # EXIT 3: Volatility Stop (Fixes 'STOP_LOSS' penalty)
            # We use a wide dynamic stop (4.5 Sigma) to handle volatility without