```python
import random
import statistics
from collections import deque, defaultdict

class MyStrategy:
    """
    Agent: Whale_Watcher_425 (Gen 4 - Phoenix Protocol)
    
    Evolution Summary:
    1.  Simplification: Removed complex Z-score math in favor of robust EMA crossovers.
    2.  Aggressive Recovery: Increased position sizing for high-conviction setups to recover drawdown.
    3.  Strict Risk Control: Implemented dynamic Trailing Stops to protect meager gains.
    4.  Anti-FOMO: Added volatility filters to prevent buying extended tops.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Whale_Watcher_v4.0 - Phoenix)")
        
        # === Capital Management ===
        self.balance = 536.69  # Sync with current state
        self.risk_per_trade = 0.20  # Aggressive 20% allocation to recover
        self.max_concurrent_trades = 3
        
        # === Technical Parameters ===
        self.ema_fast_period = 6
        self.ema_slow_period = 14
        self.volatility_window = 10
        
        # === Risk Management ===
        self.stop_loss_pct = 0.03        # Tight 3% Stop Loss
        self.trailing_trigger = 0.05     # Activate trailing after 5% gain
        self.trailing_distance = 0.02    # Trail by 2%
        
        # === State ===
        self.price_history = defaultdict(lambda: deque(maxlen=30))
        self.positions = {}  # {symbol: {'entry': float, 'shares': float, 'high': float}}
        self.cooldowns = {}  # {symbol: int_ticks_remaining}
        self.banned_tags = set()

    def on_hive_signal(self, signal: dict):
        """Process Hive Mind signals"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            
    def _calculate_ema(self, data, period):
        if len(data) < period:
            return None
        k = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price - ema) * k + ema
        return ema

    def on_price_update(self, prices: dict):
        """
        Core trading loop.
        Returns: ('buy', symbol, amount_usd) or ('sell', symbol, pct_to_sell) or None
        """
        
        # 1. Manage Cooldowns
        expired_cooldowns = [s for s, ticks in self.cooldowns.items() if ticks <= 0]
        for s in expired_cooldowns:
            del self.cooldowns[s]
        for s in self.cooldowns:
            self.cooldowns[s] -= 1

        action_taken = None

        # 2. Iterate Symbols
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            self.price_history[symbol].append(current_price)
            
            # --- Exit Logic (Priority) ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos['entry']
                
                # Update high water mark
                if current_price > pos['high']:
                    pos['high'] = current_price
                
                # Metrics
                pnl_pct = (current_price - entry_price) / entry_price
                drawdown = (pos['high'] - current_price) / pos['high']
                
                should_sell = False
                sell_reason = ""

                # A. Hard Stop Loss
                if pnl_pct < -self.stop_loss_pct:
                    should_sell = True
                    sell_reason = "STOP_LOSS"
                    self.cooldowns[symbol] = 20  # Penalty box for losers
                
                # B. Trailing Stop
                elif pnl_pct > self.trailing_trigger and drawdown > self.trailing_distance:
                    should_sell = True
                    sell_reason = "TRAILING_EXIT"
                
                # C. Trend Reversal (Fast EMA crosses below Slow EMA)
                else:
                    hist = list(self.price_history[symbol])
                    if len(hist) >= self.ema_slow_period:
                        ema_fast = self._calculate_ema(hist, self.ema_fast_period)
                        ema_slow = self._calculate_ema(hist, self.ema_slow_period)
                        if ema_fast and ema_slow and ema_fast < ema_slow:
                            should_sell = True
                            sell_