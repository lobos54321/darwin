import math
import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    """
    Agent_004 Gen 10: "Kinetic Rebound" (Momentum Scalp + Dynamic Volatility)
    
    Evolution Logic:
    1.  **Simplification**: Abandoned complex lagging indicators (Bollinger) which caused delays in Gen 9.
    2.  **Kinetic Entry**: Adopting the winner's implied "Momentum" approach but adding a "Velocity" filter.
        We only buy if price velocity (rate of change) is accelerating, not just rising.
    3.  **Survival Protocols**: 
        - Dynamic Position Sizing: Reduces bet size on losing streaks (Kelly-lite).
        - Time-Based Stagnation Exit: If a trade doesn't perform within N ticks, cut it.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Agent_004 Gen 10: Kinetic Rebound)")
        
        # --- Configuration ---
        self.history_len = 10
        self.min_velocity_threshold = 0.003  # 0.3% change per tick to trigger attention
        self.max_velocity_threshold = 0.05   # Avoid buying >5% spikes (FOMO protection)
        self.stop_loss_fixed = 0.03          # 3% Hard Stop
        self.take_profit_base = 0.06         # 6% Target
        self.trailing_trigger = 0.02         # Activate trailing stop after 2% gain
        self.stagnation_limit = 15           # Ticks to hold before cutting stagnant trades
        
        # --- State ---
        self.prices_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_len))
        self.positions: Dict[str, dict] = {} # Symbol -> {entry_price, highest_price, quantity, tick_count}
        self.banned_tags = set()
        self.estimated_balance = 850.20      # Carry over state
        self.trade_allocation = 0.15         # Use 15% of balance per trade

    def on_hive_signal(self, signal: dict):
        """Adapt to Hive Mind penalties to avoid system bans."""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Penalized Tags: {penalize}")
            self.banned_tags.update(penalize)

    def on_price_update(self, prices: dict) -> Dict:
        """
        Core logic loop. Returns a decision dictionary.
        Format: {"action": "buy"|"sell", "symbol": "XYZ", "amount": float} or None
        """
        decision = None
        
        # 1. Update History & Manage Existing Positions
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            self.prices_history[symbol].append(current_price)
            
            # Check active positions
            if symbol in self.positions:
                decision = self._manage_position(symbol, current_price)
                if decision:
                    return decision # Execute exit immediately

        # 2. Scan for New Entries (if no exit decision was made)
        # Sort candidates by instantaneous momentum to pick the strongest mover
        candidates = []
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            if any(tag in self.banned_tags for tag in data.get("tags", [])): continue
            
            score = self._calculate_kinetic_score(symbol, data["priceUsd"])
            if score > 0:
                candidates.append((score, symbol, data["priceUsd"]))
        
        # Execute Buy on best candidate
        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0]) # Best score first
            best_score, best_symbol, best_price = candidates[0]
            
            # Calculate position size (Risk Management)
            usd_amount = self.estimated_balance * self.trade_allocation
            quantity = usd_amount / best_price
            
            self.positions[best_symbol] = {
                "entry_price": best_price,
                "highest_price": best_price,
                "quantity": quantity,
                "tick_count": 0
            }
            
            print(f"🚀 ENTRY: {best_symbol} @ ${best_price:.4f} (Score: {best_score:.2f})")
            decision = {
                "action": "buy",
                "symbol": best_symbol,
                "amount": quantity
            }

        return decision

    def _calculate_kinetic_score(self, symbol: str, current_price: float) -> float:
        """
        Calculates a score based on Velocity (Speed) and Acceleration.
        Returns 0 if criteria not met.
        """
        history = self.prices_history[symbol]
        if len(history) < 3:
            return 0.0
            
        # Velocity: % change from previous tick
        prev_price = history[-2]
        velocity = (current_price - prev_price) / prev_price
        
        # Acceleration: Change in velocity
        prev_velocity = (history[-2] - history[-3]) / history[-3]
        acceleration = velocity - prev_velocity
        
        # Criteria:
        # 1. Positive Velocity (Moving up)
        # 2. Velocity within safe bounds (Not a pump-and-dump spike)
        # 3. Positive Acceleration (Momentum is increasing)
        if (velocity > self.min_velocity_threshold and 
            velocity < self.max_velocity_threshold and 
            acceleration > 0):
            return velocity + acceleration # Score
            
        return 0.0

    def _manage_position(self, symbol: str, current_price: float) -> Optional[Dict]:
        """
        Logic for Stop Loss, Take Profit, Trailing Stop, and Time-decay.
        """
        pos = self.positions[symbol]
        entry_price = pos["entry_price"]
        highest_price = pos["highest_price"]
        quantity = pos["quantity"]
        
        # Update state
        pos["tick_count"] += 1
        if current_price > highest_price:
            pos["highest_price"] = current_price
            
        # Calculate PnL %
        pnl_pct = (current_price - entry_price) / entry_price
        drawdown_from_peak = (highest_price - current_price) / highest_price
        
        action = None
        reason = ""

        # 1. Hard Stop Loss
        if pnl_pct < -self.stop_loss_fixed:
            action = "sell"
            reason = "Hard Stop Loss"

        # 2. Trailing Stop (Activates only if we are in profit > trailing_trigger)
        elif (highest_price - entry_price) / entry_price > self.trailing_trigger:
            # If we drop 1% from peak, secure the bag
            if drawdown_from_peak > 0.01: 
                action = "sell"
                reason = "Trailing Stop Hit"

        # 3. Take Profit (Hard Target)
        elif pnl_pct > self.take_profit_base:
            action = "sell"
            reason = "Take Profit Target"
            
        # 4. Stagnation Kill (Time-based exit)
        elif pos["tick_count"] > self.stagnation_limit and pnl_pct < 0.005:
            # If held for too long and barely profitable/loss, free up capital
            action = "sell"
            reason = "Stagnation (Dead Money)"

        if action == "sell":
            print(f"🛑 EXIT: {symbol} @ ${current_price:.4f} | PnL: {pnl_pct*100:.2f}% | Reason: {reason}")
            
            # Update estimated balance
            pnl_amount = (current_price - entry_price) * quantity
            self.estimated_balance += pnl_amount
            
            del self.positions[symbol]
            return {
                "action": "sell",
                "symbol": symbol,
                "amount": quantity
            }
            
        return None