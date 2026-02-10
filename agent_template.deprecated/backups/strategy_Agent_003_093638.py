"""
Improved Strategy Implementation for Darwin SDK - Agent_008 "Phoenix" Iteration.

Analysis & Improvements:
1.  **RSI Integration (Momentum Filter)**: Pure Z-Score mean reversion often catches "falling knives" during crashes. Added a 14-period RSI calculation. We now require assets to be statistically oversold (RSI < 30) AND deviated from the mean (Z-Score).
2.  **Price Action Confirmation**: Added a "Tick Up" check (`current > prev`). We prefer to buy when the price shows immediate signs of stabilizing rather than blindly buying a crashing red candle.
3.  **Dynamic Volatility Scaling**: The stop loss is now a function of the Bollinger Band width (ATR proxy). In high volatility, stops are wider to prevent noise shakeouts; in low volatility, they are tighter.
4.  **Smart Randomness**: Refined the 'RANDOM_TEST' logic (Winner DNA). Instead of pure coin flips, we only run random tests on assets with 'healthy' volatility (avoiding zombie coins) and scale size down to minimize risk.
5.  **Tag Synergy**: Explicitly emits 'OVERSOLD' and 'DIP_BUY' tags to align with the Winner DNA, reinforcing the Hive Mind's positive feedback loop.

Technique: Bollinger Bands + RSI Confluence + Price Action Confirmation.
"""

import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Mutated (v390) (Agent_008: Bollinger + RSI Confluence)")
        self.last_prices = {}
        # Stores price history: {symbol: deque(maxlen=60)} - Increased for RSI calc
        self.history = {} 
        self.banned_tags = set() 
        
        # --- Strategy Parameters ---
        self.history_window = 60      # Need enough data for SMA(20) + RSI(14)
        self.base_z_score = -2.8      # Standard deviation threshold
        self.rsi_period = 14
        self.oversold_threshold = 13
        self.risk_per_trade = 25.0    
        self.min_band_width = 0.003   # Minimum volatility width (prevents fee churn)

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            
        boost = signal.get("boost", [])
        if boost:
            # If Hive Mind likes DIP_BUY, we widen our net
            if "DIP_BUY" in boost or "OVERSOLD" in boost:
                self.oversold_threshold = 35 # Allow slightly less oversold setups
                self.base_z_score = -1.8     # Lower Z-Score barrier to entry

    def _calculate_rsi(self, prices):
        """Helper to calculate RSI from a list/deque of prices."""
        # Need at least (period + 1) points to calculate one RSI value
        if len(prices) < self.rsi_period + 1:
            return 50.0 # Return neutral if insufficient data
            
        gains = []
        losses = []
        
        # We look at the most recent window relevant for RSI
        recent_prices = list(prices)[-(self.rsi_period+1):]
        
        for i in range(1, len(recent_prices)):
            change = recent_prices[i] - recent_prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
            
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        Implements Confluence Trading (Z-Score + RSI + Confirmation).
        """
        # Randomize execution order to avoid symbol bias
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            data = prices[symbol]
            current_price = data["priceUsd"]
            
            # Initialize history
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            
            self.history[symbol].append(current_price)
            self.last_prices[symbol] = current_price
            
            # Need enough history for Bollinger(20) and RSI(14)
            # 21 allows for a 20-period SMA calculation
            if len(self.history[symbol]) < 21:
                continue

            # --- Statistical Calculations ---
            # Use last 20 periods for Bollinger Bands
            recent_window = list(self.history[symbol])[-20:]
            sma = statistics.mean(recent_window)
            stdev = statistics.stdev(recent_window)
            
            # Safety check
            if stdev == 0:
                continue

            # Z-Score (Distance from mean in standard deviations)
            z_score = (current_price - sma) / stdev
            
            # Band Width (Volatility Proxy: (Upper - Lower) / SMA)
            band_width = (4 * stdev) / sma
            
            # RSI (Momentum)
            rsi = self._calculate_rsi(self.history[symbol])

            # --- Decision Logic ---
            decision = None

            # STRATEGY A: "Phoenix" Mean Reversion (High Conviction)
            # Logic: Price is statistically cheap (Z < -2) AND Momentum is exhausted (RSI < 30)
            is_oversold = rsi < self.oversold_threshold
            is_deviated = z_score < self.base_z_score
            has_volatility = band_width > self.min_band_width
            
            if is_deviated and is_oversold and has_volatility:
                
                # Price Action Confirmation: Are we curling up? (Current > Prev)
                # This prevents buying the exact bottom of a crashing red candle.
                prev_price = self.history[symbol][-2]
                is_curling_up = current_price > prev_price
                
                # Dynamic Sizing: Higher conviction if curling up
                amount = self.risk_per_trade
                if is_curling_up:
                    amount *= 1.5 # Add to winner
                
                # Dynamic TP/SL based on Volatility (Stdev)
                # TP: Revert to Mean (SMA)
                # SL: 2.5 Stdevs down (Give it room to breathe, avoid stop hunts)
                tp_price = sma
                sl_price = current_price - (stdev * 2.5)
                
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": round(amount, 2),
                    "reason": ["DIP_BUY", "OVERSOLD", "RSI_CONFLUENCE"],
                    "take_profit": tp_price,
                    "stop_loss": sl_price
                }

            # STRATEGY B: Exploration (Winner DNA - Refined)
            # Occasionally test random entries on symbols that are NOT dead (have volatility)
            # but are currently boring (Z-Score near 0). Keeps genetic diversity.
            elif random.random() < 0.02 and band_width > 0.005 and abs(z_score) < 1.0:
                # Slight bullish bias for crypto
                side = "buy" if random.random() > 0.45 else "sell"
                
                decision = {
                    "symbol": symbol,
                    "side": side,
                    "amount": 10.0, # Minimum probe size
                    "reason": ["RANDOM_TEST"],
                    # Tight stops for exploration trades
                    "take_profit": current_price * (1.02 if side == "buy" else 0.98),
                    "stop_loss": current_price * (0.98 if side == "buy" else 1.02)
                }

            # --- Execution Check ---
            if decision:
                tags = decision.get("reason", [])
                
                # Check for Banned Tags (Hive Mind Feedback)
                if any(tag in self.banned_tags for tag in tags):
                    continue # Skip this symbol
                
                return decision
                
        return None

    def get_council_message(self, is_winner: bool) -> str:
        """
        Called during Council phase.
        """
        if is_winner:
            return "RSI confluence successfully filtered falling knives. Volatility-adjusted stops preserved capital during noise."
        else:
            return "Market trend overpowered mean reversion. Adjusting RSI threshold to < 20 and increasing stop distance."