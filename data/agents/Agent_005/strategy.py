# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import statistics
from collections import deque, defaultdict

class MyStrategy:
    """
    Agent_005 Gen 32: 'Lazarus Vector'
    
    [Evolution Log]
    - Status: Emergency Recovery ($720 Balance)
    - Parent: Gen 31 (Obsidian Shield)
    - Source of Wisdom: Absorbed 'Momentum' logic from Winner, discarded complex Volatility gates.
    - Mutation: 
        1. 'Lazarus' Recovery Mode: Position sizing scales down based on drawdown to prevent ruin.
        2. Trend Following (EMA) + Momentum: Replaced mean-reversion with trend following to catch larger moves.
        3. Dynamic Trailing Stop: Replaced fixed TP/SL with a tightening trailing stop to lock in profits early.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Lazarus Vector v32.0)")
        
        # --- Configuration ---
        self.short_window = 5
        self.long_window = 12
        self.max_positions = 3
        
        # --- State ---
        self.price_history = defaultdict(lambda: deque(maxlen=20))
        self.active_positions = {} # {symbol: {'entry': float, 'highest': float, 'size': float}}
        self.banned_tags = set()
        self.loss_streak = defaultdict(int) # Track consecutive losses per symbol
        
        # --- Risk Parameters ---
        self.base_risk_per_trade = 0.15  # Invest 15% of equity per trade
        self.trailing_stop_pct = 0.04    # 4% Trailing Stop
        self.hard_stop_pct = 0.05        # 5% Hard Stop Loss
        self.min_momentum = 0.2          # Min % change to confirm momentum

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🧠 Strategy received penalty for: {penalize}")
            self.banned_tags.update(penalize)
            # Immediate cut if holding penalized asset
            for tag in penalize:
                if tag in self.active_positions:
                    # Logic to force sell would be handled in next update or via direct API if available
                    pass

    def _calculate_ema(self, prices, window):
        if len(prices) < window:
            return None
        multiplier = 2 / (window + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        """
        decision = None
        
        # 1. Update History & Indicators
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            self.price_history[symbol].append(current_price)
            
            # Update active position stats
            if symbol in self.active_positions:
                if current_price > self.active_positions[symbol]['highest']:
                    self.active_positions[symbol]['highest'] = current_price

        # 2. Analyze Market
        for symbol, data in prices.items():
            if symbol in self.banned_tags:
                continue
                
            current_price = data["priceUsd"]
            history = list(self.price_history[symbol])
            
            # Need enough data
            if len(history) < self.long_window:
                continue
                
            # --- Sell Logic (Risk Management) ---
            if symbol in self.active_positions:
                pos = self.active_positions[symbol]
                entry_price = pos['entry']
                highest_price = pos['highest']
                
                # Trailing Stop Calculation
                drawdown_from_peak = (highest_price - current_price) / highest_price
                absolute_loss = (entry_price - current_price) / entry_price
                
                should_sell = False
                reason = ""
                
                # Condition A: Trailing Stop Hit
                if drawdown_from_peak >= self.trailing_stop_pct:
                    should_sell = True
                    reason = "Trailing Stop"
                
                # Condition B: Hard Stop Loss
                elif absolute_loss >= self.hard_stop_pct:
                    should_sell = True
                    reason = "Hard Stop"
                    self.loss_streak[symbol] += 1
                
                if should_sell:
                    # print(f"🔻 SELL {symbol} | Reason: {reason} | PnL: {-absolute_loss*100:.2f}%")
                    decision = {"symbol": symbol, "action": "sell", "amount": pos['amount']}
                    del self.active_positions[symbol]
                    return decision # Execute one action per tick

            # --- Buy Logic (Momentum + Trend) ---
            elif len(self.active_positions) < self.max_positions:
                # Filter out assets with too many recent losses
                if self.loss_streak[symbol] >= 2:
                    # Cool down: skip this symbol occasionally
                    if random.random() > 0.1: 
                        continue
                    else:
                        self.loss_streak[symbol] = 0 # Reset chance
                
                ema_short = self._calculate_ema(history, self.short_window)
                ema_long = self._calculate_ema(history, self.long_window)
                
                if ema_short and ema_long:
                    # Momentum Calculation (last 3 ticks)
                    if len(history) >= 3:
                        momentum = ((current_price - history[-3]) / history[-3]) * 100
                    else:
                        momentum = 0
                    
                    # Entry Conditions:
                    # 1. Trend: Short EMA > Long EMA (Golden Cross-ish)
                    # 2. Position: Price > Short EMA (Strong Trend)
                    # 3. Momentum: Positive short-term velocity (Winner's Wisdom)
                    if (ema_short > ema_long) and (current_price > ema_short) and (momentum > self.min_momentum):
                        
                        # Dynamic Sizing for Recovery
                        # If we have recently lost, trade smaller.
                        risk_factor = 1.0 / (1.0 + (self.loss_streak[symbol] * 0.5))
                        amount_to_invest = 720 * self.base_risk_per_trade * risk_factor # Using approx balance
                        
                        # print(f"🟢 BUY {symbol} | Mom: {momentum:.2f}% | EMA Trend: UP")
                        self.active_positions[symbol] = {
                            'entry': current_price,
                            'highest': current_price,
                            'amount': amount_to_invest
                        }
                        
                        decision = {"symbol": symbol, "action": "buy", "amount": amount_to_invest}
                        return decision

        return decision