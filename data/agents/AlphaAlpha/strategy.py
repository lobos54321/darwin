# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import math
import statistics
from collections import deque
import time

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (AlphaAlpha v4.0 - Chimera Evolution)")
        
        # --- Genotype (Parameters) ---
        self.window_size = 15           # Lookback window for volatility/MA
        self.z_score_buy = -1.8         # Buy when price is 1.8 std devs below mean (Mean Reversion)
        self.z_score_sell = 1.5         # Sell when price is 1.5 std devs above mean
        self.stop_loss_pct = 0.05       # 5% Hard Stop Loss (Widened to prevent noise shakeout)
        self.trailing_trigger = 0.08    # Activate trailing stop after 8% gain
        self.trailing_distance = 0.03   # Trail by 3%
        self.max_hold_time = 300        # Max hold time in seconds (Time-based stop)
        self.allocation_per_trade = 0.2 # Use 20% of capital per trade
        
        # --- Phenotype (State) ---
        self.price_history = {}         # {symbol: deque(maxlen=window_size)}
        self.positions = {}             # {symbol: {entry: float, high: float, time: float, amount: float}}
        self.banned_tags = set()        # Hive Mind Penalties
        self.last_decision_time = 0
        self.cooldowns = {}             # {symbol: timestamp}

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind to adapt evolution"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🧬 Gene suppression (Penalty): {penalize}")
            self.banned_tags.update(penalize)
            
        boost = signal.get("boost", [])
        if boost:
            # In v4.0, we treat boosts as volatility stabilizers
            pass

    def get_indicators(self, symbol, current_price):
        """Calculate statistical indicators"""
        history = self.price_history.get(symbol)
        if not history or len(history) < self.window_size:
            return None
        
        prices = list(history)
        mean_price = statistics.mean(prices)
        stdev = statistics.stdev(prices) if len(prices) > 1 else 0
        
        if stdev == 0:
            return None
            
        z_score = (current_price - mean_price) / stdev
        return {"mean": mean_price, "std": stdev, "z": z_score}

    def on_price_update(self, prices: dict):
        """
        Main decision loop.
        """
        current_time = time.time()
        decision = None
        
        # 1. Update Data & Check Exits
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Initialize history
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(current_price)
            
            # --- Position Management (Risk Control) ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Update High Watermark
                if current_price > pos['high']:
                    pos['high'] = current_price
                
                # Calculate PnL %
                pnl_pct = (current_price - pos['entry']) / pos['entry']
                
                # A. Hard Stop Loss
                if pnl_pct < -self.stop_loss_pct:
                    print(f"🛡️ STOP LOSS triggered on {symbol} at {pnl_pct:.2%}")
                    return {"symbol": symbol, "action": "SELL", "amount": pos['amount']}
                
                # B. Trailing Stop Profit
                drawdown_from_high = (pos['high'] - current_price) / pos['high']
                if pnl_pct > self.trailing_trigger and drawdown_from_high > self.trailing_distance:
                    print(f"💰 TRAILING TAKE PROFIT on {symbol} (High: {pos['high']})")
                    return {"symbol": symbol, "action": "SELL", "amount": pos['amount']}
                
                # C. Time-based Exit (Stagnation killer)
                if (current_time - pos['time']) > self.max_hold_time and pnl_pct < 0.01:
                    print(f"⌛ TIME DECAY exit on {symbol}")
                    return {"symbol": symbol, "action": "SELL", "amount": pos['amount']}

                # D. Mean Reversion Exit (Overbought)
                stats = self.get_indicators(symbol, current_price)
                if stats and stats['z'] > self.z_score_sell:
                    print(f"📈 Z-SCORE EXIT on {symbol} (Z: {stats['z']:.2f})")
                    return {"symbol": symbol, "action": "SELL", "amount": pos['amount']}

        # 2. Scan for Entries (Only if no decision made yet)
        # Sort by volatility to find moving assets, but avoid banned ones
        candidates = []
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            if symbol in self.banned_tags: continue
            if self.cooldowns.get(symbol, 0) > current_time: continue
            
            stats = self.get_indicators(symbol, data["priceUsd"])
            if stats:
                candidates.append((symbol, stats, data["priceUsd"]))
        
        # Look for deep value (Oversold)
        for symbol, stats, price in candidates:
            # Logic: Buy if price is significantly below mean (Mean Reversion)
            # AND volatility is sufficient to bounce back
            if stats['z'] < self.z_score_buy:
                print(f"🚀 ENTRY SIGNAL: {symbol} (Z: {stats['z']:.2f} | Price: {price})")
                
                # Record Position
                amount = self.allocation_per_trade # Simplified amount logic
                self.positions[symbol] = {
                    'entry': price,
                    'high': price,
                    'time': current_time,
                    'amount': amount
                }
                
                return {"symbol": symbol, "action": "BUY", "amount": amount}
                
        return None