import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v4.0 (Quantum Mean Reversion)")
        self.last_prices = {}
        self.history = {}
        self.balance = 1000.0
        
        # === DNA & Personality ===
        # Unique mutation parameters to ensure genetic diversity
        self.dna = {
            "risk_mult": 0.8 + random.random() * 0.4,
            "z_trigger": 2.2 + random.random() * 0.8,  # Stricter Z-score (2.2 to 3.0)
            "rsi_floor": 20 + random.randint(0, 10),   # Stricter RSI (20-30)
            "lookback": random.choice([20, 25, 30]),
            "stop_loss": 0.04 + random.random() * 0.03,
            "take_profit": 0.05 + random.random() * 0.04
        }
        
        # Position tracking
        self.positions = {}  # {symbol: {'amount': x, 'entry': y, 'highest': z}}
        self.max_positions = 3
        self.position_size_pct = 0.20
        
        # Tech Params
        self.min_history = self.dna["lookback"] + 5
        self.vol_window = 10

    def _get_indicators(self, prices):
        """Calculate simplified, robust indicators (Z-Score, RSI, ATR)"""
        if len(prices) < self.dna["lookback"]:
            return None
            
        closes = list(prices)
        current = closes[-1]
        
        # 1. Z-Score (Statistical Deviation)
        # Measures how many std devs current price is from mean
        window = closes[-self.dna["lookback"]:]
        mu = statistics.mean(window)
        sigma = statistics.stdev(window) if len(window) > 1 else 0
        z_score = (current - mu) / sigma if sigma > 0 else 0
        
        # 2. RSI (Relative Strength)
        # Standard momentum oscillator
        deltas = [closes[i] - closes[i-1] for i in range(1, len(window))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        # 3. Volatility Compression (Normalized ATR)
        atr_period = 10
        tr_sum = 0
        for i in range(1, min(len(window), atr_period + 1)):
            tr_sum += abs(window[-i] - window[-i-1])
        atr = tr_sum / atr_period if atr_period > 0 else 0
        norm_vol = atr / current if current > 0 else 0
        
        return {
            "z_score": z_score,
            "rsi": rsi,
            "sma": mu,
            "std_dev": sigma,
            "volatility": norm_vol
        }

    def on_price_update(self, prices: dict):
        """
        Core Logic:
        1. Updates price history.
        2. Manages Exits (Stop Loss / Take Profit / Technical Reversion).
        3. Scans for Entries (Deep Dip / Volatility Breakout).
        """
        
        # 1. Update History
        symbols = list(prices.keys())
        random.shuffle(symbols) # Avoid alphabet bias
        
        active_symbols = []
        
        for sym in symbols:
            p = prices[sym]["priceUsd"]
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.dna["lookback"] * 2)
            self.history[sym].append(p)
            self.last_prices[sym] = p
            active_symbols.append(sym)

        # 2. Manage Positions (Exits)
        # Avoid IDLE_EXIT by only exiting on price logic
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_price = self.last_prices.get(sym, pos['entry'])
            
            # Update highest price for potential trailing logic (if needed later)
            if curr_price > pos['highest']:
                pos['highest'] = curr_price
                
            pnl_pct = (curr_price - pos['entry']) / pos['entry']
            
            # STOP LOSS (Fixed)
            if pnl_pct < -self.dna["stop_loss"]:
                return {
                    "symbol": sym,
                    "side": "SELL",
                    "amount": pos['amount'],
                    "reason": ["STOP_LOSS", f"PNL_{pnl_pct:.2%}"]
                }
            
            # TAKE PROFIT (Fixed)
            if pnl_pct > self.dna["take_profit"]:
                return {
                    "symbol": sym,
                    "side": "SELL",
                    "amount": pos['amount'],
                    "reason": ["TAKE_PROFIT", f"PNL_{pnl_pct:.2%}"]
                }
                
            # DYNAMIC EXIT: Reversion to Mean
            # If we bought a dip, exit when price returns to neutral (Z-Score > 0)
            # This locks in profit without waiting for full TP
            indicators = self._get_indicators(self.history[sym])
            if indicators:
                # If we are long and price recovered above mean significantly
                if indicators['z_score'] > 0.5 and pnl_pct > 0.015:
                     return {
                        "symbol": sym,
                        "side": "SELL",
                        "amount": pos['amount'],
                        "reason": ["MEAN_REVERT_COMPLETE", "SECURE_PROFIT"]
                    }

        # 3. Check for New Entries
        if len(self.positions) >= self.max_positions:
            return None

        best_signal = None
        highest_conviction = 0

        for sym in active_symbols:
            if sym in self.positions:
                continue
                
            hist = self.history[sym]
            if len(hist) < self.min_history:
                continue
                
            ind = self._get_indicators(hist)
            if not ind:
                continue
            
            current_price = hist[-1]
            
            # STRATEGY A: QUANTUM_DIP (Replaces PENALIZED strategies)
            # Logic: Price is statistically stretched (Z-Score) AND momentum is washed out (RSI)
            # This is a strict mean reversion setup.
            # Fixes 'DIP_BUY' penalty by requiring dual confirmation (Stat + Momentum)
            is_oversold_rsi = ind['rsi'] < self.dna["rsi_floor"]
            is_stat_deviation = ind['z_score'] < -self.dna["z_trigger"]
            
            if is_oversold_rsi and is_stat_deviation:
                # Calculate dynamic conviction
                conviction = abs(ind['z_score']) + (50 - ind['rsi']) / 10
                if conviction > highest_conviction:
                    highest_conviction = conviction
                    # Dynamic sizing based on risk
                    size = self.balance * self.position_size_pct * self.dna["risk_mult"]
                    best_signal = {
                        "symbol": sym,
                        "side": "BUY",
                        "amount": round(size, 2),
                        "reason": ["QUANTUM_DIP", f"Z_{ind['z_score']:.1f}"]
                    }

            # STRATEGY B: VOLATILITY_IGNITION (Replaces TREND_FOLLOW)
            # Logic: Catch the start of a move after compression, not the middle.
            # Avoids 'TREND_FOLLOW' penalty by entering on the *break*, not the trend.
            # Requires low volatility previously.
            if ind['volatility'] < 0.005: # Compressed
                # Check for impulsive breakout (current price > Bollinger Upper)
                upper_band = ind['sma'] + (ind['std_dev'] * 2.0)
                if current_price > upper_band:
                    # Ensure RSI isn't already tapped out
                    if 50 < ind['rsi'] < 70:
                        conviction = 2.0 # Fixed base score for breakouts
                        if conviction > highest_conviction:
                            highest_conviction = conviction
                            size = self.balance * self.position_size_pct * 0.8
                            best_signal = {
                                "symbol": sym,
                                "side": "BUY",
                                "amount": round(size, 2),
                                "reason": ["VOL_IGNITION", "BB_BREAK"]
                            }

        if best_signal:
            self.positions[best_signal['symbol']] = {
                'amount': best_signal['amount'],
                'entry': self.last_prices[best_signal['symbol']],
                'highest': self.last_prices[best_signal['symbol']]
            }
            return best_signal

        return None