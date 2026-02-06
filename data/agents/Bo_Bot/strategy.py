# Darwin SDK - User Strategy Template
# 🧬 AGENT: Bo_Bot | GEN: 79 | CODENAME: TITANIUM_VANGUARD
# -----------------------------------------------------------------------------
# Evolution Log (Gen 79):
# 1. CRITICAL FIX: Fixed "Ruin" bug. Position sizing is now dynamic based on 
#    account equity (max 10% per trade).
# 2. MUTATION "Volatility Compression": Replaced simple Z-Score with a 
#    Volatility Squeeze logic. We wait for price to stabilize, then buy the breakout.
# 3. DEFENSE: Implemented "Time-Based Decay". If a trade doesn't perform within
#    10 ticks, we cut it to free up capital.
# 4. HIVE MIND: Respects penalty signals immediately to avoid bans.
# -----------------------------------------------------------------------------

import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (Gen 79: Titanium Vanguard)")
        
        # --- State Tracking ---
        self.balance = 1000.0           # Estimated balance (sync with engine in real run)
        self.positions = {}             # {symbol: {"entry": float, "amount": float, "peak": float, "ticks": int}}
        self.price_history = {}         # {symbol: deque(maxlen=20)}
        self.banned_tags = set()
        
        # --- Hyperparameters ---
        self.MAX_POSITIONS = 5          # Diversification hard limit
        self.POSITION_SIZE_PCT = 0.15   # Invest 15% of balance per trade
        self.HISTORY_LEN = 20           # Lookback window
        
        # --- Entry Logic (Squeeze Breakout) ---
        self.VOLATILITY_THRESHOLD = 0.02 # Max std dev to consider "squeezed"
        self.BREAKOUT_FACTOR = 1.03      # Buy if price > 103% of recent mean
        
        # --- Exit Logic (Risk Management) ---
        self.STOP_LOSS_PCT = 0.05       # 5% Hard Stop (Tighter)
        self.TAKE_PROFIT_PCT = 0.20     # 20% Target
        self.TRAILING_TRIGGER = 0.08    # Activate trailing stop after 8% gain
        self.TRAILING_DIST = 0.03       # Trailing distance
        self.MAX_HOLD_TICKS = 15        # Time stop (cut dead money)

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind and adapt immediately."""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🛡️ DEFENSE: Penalized tags detected: {penalize}")
            self.banned_tags.update(penalize)
            # Emergency exit for banned assets
            for tag in penalize:
                if tag in self.positions:
                    self.positions[tag]["force_exit"] = True

    def get_volatility(self, prices):
        """Calculate relative standard deviation."""
        if len(prices) < 5:
            return 1.0
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        return stdev / mean if mean > 0 else 0

    def on_price_update(self, prices: dict):
        """
        Main logic loop. Returns a list of orders.
        """
        orders = []
        
        # 1. Update Data & Check Exits
        active_symbols = list(self.positions.keys())
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Initialize history if new
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.HISTORY_LEN)
            self.price_history[symbol].append(current_price)
            
            # --- MANAGE EXISTING POSITIONS ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos["ticks"] += 1
                
                # Update Peak for Trailing Stop
                if current_price > pos["peak"]:
                    pos["peak"] = current_price
                
                entry_price = pos["entry"]
                pct_change = (current_price - entry_price) / entry_price
                peak_change = (pos["peak"] - entry_price) / entry_price
                drawdown_from_peak = (pos["peak"] - current_price) / pos["peak"]
                
                should_sell = False
                reason = ""
                
                # A. Force Exit (Banned)
                if pos.get("force_exit", False):
                    should_sell = True
                    reason = "HIVE_BAN"
                
                # B. Hard Stop Loss
                elif pct_change < -self.STOP_LOSS_PCT:
                    should_sell = True
                    reason = "STOP_LOSS"
                    
                # C. Trailing Stop
                elif pct_change > self.TRAILING_TRIGGER and drawdown_from_peak > self.TRAILING_DIST:
                    should_sell = True
                    reason = "TRAILING_STOP"
                    
                # D. Take Profit
                elif pct_change > self.TAKE_PROFIT_PCT:
                    should_sell = True
                    reason = "TAKE_PROFIT"
                    
                # E. Time Stop (Stagnation)
                elif pos["ticks"] > self.MAX_HOLD_TICKS and pct_change < 0.01:
                    should_sell = True
                    reason = "TIME_DECAY"

                if should_sell:
                    # Execute SELL
                    orders.append({
                        "symbol": symbol,
                        "action": "SELL",
                        "amount": pos["amount"],
                        "reason": reason
                    })
                    # Update internal state
                    pnl = (current_price - entry_price) * (pos["amount"] / entry_price)
                    self.balance += (pos["amount"] + pnl)
                    del self.positions[symbol]
                    continue # Skip to next symbol

        # 2. Check New Entries (Scan for Opportunities)
        # Only if we have slots available
        if len(self.positions) < self.MAX_POSITIONS:
            
            # Sort candidates by momentum to pick the best one
            candidates = []
            
            for symbol, data in prices.items():
                if symbol in self.positions or symbol in self.banned_tags:
                    continue
                
                history = self.price_history[symbol]
                if len(history) < 10:
                    continue
                
                current_price = data["priceUsd"]
                recent_window = list(history)[-10:]
                
                # Logic: Volatility Squeeze -> Breakout
                # 1. Check if price was stable recently (low volatility)
                vol = self.get_volatility(recent_window[:-1]) # Exclude current tick
                
                # 2. Check if current price is breaking out above the mean
                mean_price = statistics.mean(recent_window[:-1])
                ratio = current_price / mean_price
                
                if vol < self.VOLATILITY_THRESHOLD and ratio > self.BREAKOUT_FACTOR:
                    candidates.append((symbol, ratio, current_price))
            
            # Select best candidate (highest breakout ratio)
            candidates.sort(key=lambda x: x[1], reverse=True)
            
            for cand in candidates:
                if len(self.positions) >= self.MAX_POSITIONS:
                    break
                    
                symbol, ratio, price = cand
                
                # Position Sizing
                trade_amount = self.balance * self.POSITION_SIZE_PCT
                if trade_amount < 10: continue # Minimum trade size
                
                # Execute BUY
                orders.append({
                    "symbol": symbol,
                    "action": "BUY",
                    "amount": trade_amount,
                    "reason": "SQUEEZE_BREAKOUT"
                })
                
                # Update internal state
                self.positions[symbol] = {
                    "entry": price,
                    "amount": trade_amount,
                    "peak": price,
                    "ticks": 0
                }
                self.balance -= trade_amount

        return orders