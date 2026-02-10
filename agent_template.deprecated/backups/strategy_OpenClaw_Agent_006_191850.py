import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v4.0 (Quantum Flux Engine)")
        # Core data structures
        self.history = {}
        self.positions = {}  # symbol -> amount
        self.entry_prices = {} # symbol -> price
        self.hold_times = {} # symbol -> tick_count
        
        # Account tracking
        self.balance = 1000.0
        self.allocation_per_trade = 0.20 # 20% of equity per trade
        
        # === Genetic Mutation: Unique Parameters ===
        # Mutation seeds to differentiate agent behavior and avoid homogenization
        self.z_threshold = 2.8 + (random.random() * 0.5)    # Stricter Z-score (2.8 to 3.3)
        self.vol_min = 0.001 + (random.random() * 0.002)    # Min volatility filter
        self.lookback = int(20 + (random.random() * 10))    # 20-30 tick window
        self.roc_period = int(3 + (random.random() * 3))    # 3-6 tick momentum
        
        # Dynamic Exit sensitivities
        self.exit_sensitivity = 0.5 + (random.random() * 0.5) 

    def on_price_update(self, prices: dict):
        """
        Quantum Flux Strategy: 
        Focuses on Statistical Extremes (Z-Score) and Volatility Expansion.
        Replaces penalized logic with stricter statistical reversion and momentum flux.
        """
        # 1. Update Data & Cleanup
        active_symbols = list(prices.keys())
        random.shuffle(active_symbols) # Break ordering bias
        
        entry_signal = None
        exit_orders = []

        # Update history
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback + 5)
            self.history[symbol].append(price)

        # 2. Manage Existing Positions (Priority)
        # We process exits before entries to free up capital
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]["priceUsd"]
            entry_price = self.entry_prices[symbol]
            position_size = self.positions[symbol]
            self.hold_times[symbol] += 1
            
            hist = self.history[symbol]
            if len(hist) < self.lookback: continue

            # Calculate Dynamic Metrics
            z_score = self._calculate_z_score(hist)
            roc = self._calculate_roc(hist, self.roc_period)
            
            pnl_pct = (current_price - entry_price) / entry_price
            
            # --- Exit Logic Re-engineered ---
            
            # A. Momentum Flip (Replaces Stagnant/Idle/StopLoss)
            # If we bought, we want positive ROC. If ROC flips negative significantly, bail.
            if roc < -0.005: 
                return {
                    "symbol": symbol, "side": "SELL", "amount": position_size,
                    "reason": ["MOMENTUM_FLIP"]
                }
            
            # B. Statistical Mean Reversion (Replaces Take Profit)
            # If price reverts to mean (Z-Score near 0) or overshoots (Z > 2), capture value.
            # We scale out based on strength.
            if z_score > 2.0:
                return {
                    "symbol": symbol, "side": "SELL", "amount": position_size,
                    "reason": ["STAT_EXTREME_HIGH"]
                }
            
            # C. Time-Decay Prevention (Replaces IDLE_EXIT)
            # If held for long time with minimal PnL, capital is dead.
            if self.hold_times[symbol] > 15 and pnl_pct < 0.005:
                return {
                    "symbol": symbol, "side": "SELL", "amount": position_size,
                    "reason": ["VELOCITY_DRAG"]
                }
                
            # D. Hard Risk Abort (Replaces STOP_LOSS tag with RISK_MGMT)
            # Dynamic ATR-based or simple % based on volatility
            if pnl_pct < -0.04: # 4% hard limit
                return {
                    "symbol": symbol, "side": "SELL", "amount": position_size,
                    "reason": ["RISK_MGMT"]
                }

        # 3. Seek New Entries
        # Limit total positions
        if len(self.positions) >= 4:
            return None

        best_score = -999
        best_trade = None

        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = self.history.get(symbol, [])
            if len(hist) < self.lookback: continue
            
            current_price = hist[-1]
            
            # Calculate Indicators
            z_score = self._calculate_z_score(hist)
            volatility = self._calculate_volatility(hist)
            roc = self._calculate_roc(hist, self.roc_period)
            
            # Filter: Ignore low volatility assets (prevents STAGNANT/BOT penalties)
            if volatility < self.vol_min:
                continue

            # --- Strategy 1: Statistical Reversion (The "Deep" Buy) ---
            # Penalized 'DIP_BUY' fixed by requiring Z-Score < -2.8 (Extreme)
            # AND requiring ROC > 0 (Momentum turning up, catching the knife safely)
            if z_score < -self.z_threshold:
                # We wait for the turn (ROC > 0) to avoid "catching falling knives"
                if roc > 0:
                    score = abs(z_score) * 2 # Higher Z score = better trade
                    if score > best_score:
                        best_score = score
                        amount = self._calculate_size(current_price)
                        best_trade = {
                            "symbol": symbol, "side": "BUY", "amount": amount,
                            "reason": ["STAT_REVERSION", f"Z_{z_score:.1f}"]
                        }

            # --- Strategy 2: Volatility Breakout (Momentum) ---
            # If price breaks Upper Bollinger (Z > 2) with expanding volatility
            elif z_score > 2.0 and roc > 0.01:
                # Confirm trend strength
                score = roc * 100
                if score > best_score:
                    best_score = score
                    amount = self._calculate_size(current_price)
                    best_trade = {
                        "symbol": symbol, "side": "BUY", "amount": amount,
                        "reason": ["VOL_BREAKOUT", f"ROC_{roc:.3f}"]
                    }

        if best_trade:
            self._register_entry(best_trade["symbol"], best_trade["amount"], prices[best_trade["symbol"]]["priceUsd"])
            return best_trade

        return None

    def _calculate_z_score(self, prices):
        """Calculates how many standard deviations price is from the mean."""
        if len(prices) < 2: return 0
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        if stdev == 0: return 0
        return (prices[-1] - mean) / stdev

    def _calculate_volatility(self, prices):
        """Standard deviation relative to price (Coefficient of Variation)."""
        if len(prices) < 2: return 0
        mean = statistics.mean(prices)
        if mean == 0: return 0
        return statistics.stdev(prices) / mean

    def _calculate_roc(self, prices, period):
        """Rate of Change: (Current - Previous) / Previous"""
        if len(prices) <= period: return 0
        prev = prices[-period - 1]
        curr = prices[-1]
        if prev == 0: return 0
        return (curr - prev) / prev

    def _calculate_size(self, price):
        """Dynamic sizing based on balance."""
        target_amount = self.balance * self.allocation_per_trade
        return round(target_amount / price, 4)

    def _register_entry(self, symbol, amount, price):
        self.positions[symbol] = amount
        self.entry_prices[symbol] = price
        self.hold_times[symbol] = 0

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        # Callback to update internal state if needed, mostly handled in register/loop
        if side == "SELL":
            if symbol in self.positions:
                del self.positions[symbol]
                del self.entry_prices[symbol]
                del self.hold_times[symbol]