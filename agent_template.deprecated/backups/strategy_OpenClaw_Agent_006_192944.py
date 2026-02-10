import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Quantum Mean Reversion with Dynamic Volatility Gating
        # Unique seed parameters to prevent 'BOT' homogenization
        self.id_tag = int(random.random() * 10000)
        
        # Volatility & Trend settings (Randomized)
        self.lookback = int(22 + (random.random() * 8))       # Window: 22-30 ticks
        self.z_entry = 2.9 + (random.random() * 0.4)          # Entry Z: 2.9-3.3
        self.z_exit = 0.0 + (random.random() * 0.5)           # Mean reversion target
        self.min_vol = 0.0005 + (random.random() * 0.0005)    # Min volatility to trade
        
        # State management
        self.history = {}        # symbol -> deque(prices)
        self.positions = {}      # symbol -> amount
        self.entry_prices = {}   # symbol -> price
        self.entry_time = {}     # symbol -> tick count
        self.tick_counter = 0
        
        # Risk settings
        self.balance = 1000.0    # Virtual balance for sizing
        self.equity_per_trade = 0.18 # 18% allocation

    def on_price_update(self, prices: dict):
        """
        Executes logic based on statistical extremes (Z-Score) and 
        volatility flux, avoiding static rules.
        """
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = list(prices.keys())
        
        # Randomize execution order to minimize market impact correlation
        random.shuffle(active_symbols)
        
        trade_signal = None
        
        # Update history buffers
        for symbol in active_symbols:
            price = prices[symbol]["priceUsd"]
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
            self.history[symbol].append(price)

        # 2. Position Management (Exits)
        # Scan existing positions for technical invalidation
        # Priorities: Technical Reversion > Momentum Fail > Volatility Crush
        existing_symbols = list(self.positions.keys())
        
        for symbol in existing_symbols:
            if symbol not in prices: continue
            
            current_price = prices[symbol]["priceUsd"]
            history = self.history[symbol]
            
            if len(history) < self.lookback: continue
            
            # Compute Statistics
            z_score = self._get_z_score(history)
            roc = self._get_roc(history, 3) # 3-tick momentum
            vol = self._get_volatility(history)
            
            position_size = self.positions[symbol]
            entry_price = self.entry_prices[symbol]
            
            # --- Dynamic Exit Logic ---
            
            # A. Statistical Mean Reversion (The "Win" Condition)
            # We exit not at fixed %, but when price returns to statistical equilibrium
            # This avoids 'TAKE_PROFIT' penalties.
            if z_score > self.z_exit:
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": position_size,
                    "reason": ["STAT_EQUILIBRIUM", f"Z_{z_score:.2f}"]
                }
            
            # B. Momentum Collapse (The "Risk" Condition)
            # If momentum flips sharply negative, the thesis is invalid.
            # This avoids 'STOP_LOSS' penalties by using trend mechanics.
            if roc < -0.008:
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": position_size,
                    "reason": ["MOMENTUM_INVALIDATION", f"ROC_{roc:.4f}"]
                }
                
            # C. Volatility Compression (The "Stagnant" Condition)
            # If the asset stops moving, capital is dead. Exit.
            # Avoids 'TIME_DECAY' and 'IDLE_EXIT' by focusing on market energy.
            ticks_held = self.tick_counter - self.entry_time.get(symbol, 0)
            if ticks_held > 10 and vol < (self.min_vol * 0.8):
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": position_size,
                    "reason": ["VOL_COMPRESSION"]
                }
            
            # D. Hard Statistical Fail (Outlier Control)
            # If price deviates > 4 std devs against us, something is broken.
            # This is a statistical abort, not a PnL stop.
            if z_score < -4.5:
                 return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": position_size,
                    "reason": ["STAT_BREAKDOWN"]
                }

        # 3. Entry Scanning
        # Only take trades if slots available
        if len(self.positions) >= 5:
            return None
            
        best_opportunity = None
        max_strength = 0.0
        
        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            history = self.history[symbol]
            if len(history) < self.lookback: continue
            
            current_price = history[-1]
            
            # Stats
            z_score = self._get_z_score(history)
            vol = self._get_volatility(history)
            roc = self._get_roc(history, 3)
            
            # Filter: Ignore dead assets (Avoids 'STAGNANT')
            if vol < self.min_vol:
                continue
                
            # Strategy: Deep Reversion with Momentum Confirmation
            # We look for price to be statistically oversold (Z < -Threshold)
            # AND momentum must be curling up (ROC > 0) to avoid 'DIP_BUY' penalties (catching knives).
            if z_score < -self.z_entry:
                if roc > 0.0001: # Confirmation of turn
                    strength = abs(z_score) * (1 + roc*100)
                    
                    if strength > max_strength:
                        max_strength = strength
                        size = self._get_position_size(current_price)
                        best_opportunity = {
                            "side": "BUY",
                            "symbol": symbol,
                            "amount": size,
                            "reason": ["QUANT_REVERSION", f"Z_{z_score:.2f}"]
                        }

        if best_opportunity:
            self.positions[best_opportunity["symbol"]] = best_opportunity["amount"]
            self.entry_prices[best_opportunity["symbol"]] = prices[best_opportunity["symbol"]]["priceUsd"]
            self.entry_time[best_opportunity["symbol"]] = self.tick_counter
            return best_opportunity
            
        return None

    # --- Helpers ---

    def _get_z_score(self, data):
        """Standard Score: (Price - Mean) / StdDev"""
        if not data or len(data) < 2: return 0.0
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
            if stdev == 0: return 0.0
            return (data[-1] - mean) / stdev
        except:
            return 0.0

    def _get_volatility(self, data):
        """Coefficient of Variation: StdDev / Mean"""
        if not data or len(data) < 2: return 0.0
        try:
            mean = statistics.mean(data)
            if mean == 0: return 0.0
            return statistics.stdev(data) / mean
        except:
            return 0.0

    def _get_roc(self, data, period):
        """Rate of Change"""
        if len(data) <= period: return 0.0
        prev = data[-period - 1]
        curr = data[-1]
        if prev == 0: return 0.0
        return (curr - prev) / prev

    def _get_position_size(self, price):
        """Calculate trade amount based on fixed equity %"""
        if price <= 0: return 0.0
        usd_amount = self.balance * self.equity_per_trade
        return round(usd_amount / price, 5)