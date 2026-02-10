import math
import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, List, Any

class MyStrategy:
    """
    Agent_005 Gen 1: "Velocity Breakout"
    
    Correction for Penalties (DIP_BUY, OVERSOLD, RSI_CONFLUENCE):
    1.  **Inversion**: Instead of buying dips (mean reversion), we buy strict volatility breakouts (momentum).
    2.  **Z-Score Entry**: We only enter if price exceeds 2.0 standard deviations above the mean (Upper Bollinger Band breach).
    3.  **Strength Confirmation**: Requires positive linear regression slope (trend) to confirm the breakout isn't noise.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Agent_005: Velocity Breakout)")
        
        # --- Configuration ---
        self.history_len = 30
        self.z_entry_threshold = 2.0     # Strict: Only buy if price is statistically high (Breakout)
        self.min_history = 20            # Need enough data for Stdev
        
        # Risk Settings
        self.stop_loss_fixed = 0.03      # 3% Max Risk
        self.take_profit = 0.08          # 8% Target
        self.trailing_arm = 0.03         # Arm trailing stop after 3% profit
        self.trailing_gap = 0.015        # 1.5% trailing distance
        
        # --- State ---
        self.prices_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_len))
        self.positions: Dict[str, dict] = {} 
        self.virtual_balance = 1000.0    # Simulation balance
        self.bet_size = 0.2              # 20% of equity per trade

    def on_price_update(self, prices: dict) -> Dict:
        """
        Receives price updates, manages exits, and checks for breakout entries.
        """
        decision = None
        
        # 1. Process Data & Check Exits first (Priority)
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            self.prices_history[symbol].append(current_price)
            
            if symbol in self.positions:
                exit_signal = self._check_exits(symbol, current_price)
                if exit_signal:
                    return exit_signal  # Return immediately on exit
        
        # 2. Check Entries (only if no exit happened)
        # We look for the strongest breakout candidate
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = self.prices_history[symbol]
            if len(history) < self.min_history: continue
            
            current_price = data["priceUsd"]
            
            # Statistical Calculation
            avg = statistics.mean(history)
            stdev = statistics.stdev(history)
            
            if stdev == 0: continue
            
            z_score = (current_price - avg) / stdev
            
            # LOGIC: Buy only on significant strength (Z > 2.0)
            # This completely avoids 'DIP_BUY' penalties.
            if z_score > self.z_entry_threshold:
                candidates.append({
                    'symbol': symbol,
                    'price': current_price,
                    'z_score': z_score
                })
        
        # Select best candidate (Highest Z-Score = Strongest Breakout)
        if candidates:
            # Sort by Z-score descending
            best = max(candidates, key=lambda x: x['z_score'])
            
            # Position Sizing
            usd_size = self.virtual_balance * self.bet_size
            amount = usd_size / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'highest_price': best['price'],
                'amount': amount
            }
            
            decision = {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['BREAKOUT', 'MOMENTUM', f"Z_SCORE:{best['z_score']:.2f}"]
            }
            
        return decision

    def _check_exits(self, symbol: str, current_price: float) -> Optional[Dict]:
        """
        Manages risk: Fixed Stop Loss, Take Profit, and Trailing Stop.
        """
        pos = self.positions[symbol]
        entry = pos['entry_price']
        high = pos['highest_price']
        amount = pos['amount']
        
        # Update High Water Mark
        if current_price > high:
            pos['highest_price'] = current_price
            high = current_price
            
        pnl_pct = (current_price - entry) / entry
        drawdown_from_peak = (high - current_price) / high
        
        reason = []
        should_sell = False
        
        # 1. Hard Stop Loss
        if pnl_pct < -self.stop_loss_fixed:
            should_sell = True
            reason.append('STOP_LOSS')
            
        # 2. Take Profit
        elif pnl_pct > self.take_profit:
            should_sell = True
            reason.append('TAKE_PROFIT')
            
        # 3. Trailing Stop
        # Activate only if we have reached the "arming" threshold
        elif ((high - entry) / entry) > self.trailing_arm:
            if drawdown_from_peak > self.trailing_gap:
                should_sell = True
                reason.append('TRAILING_STOP')

        if should_sell:
            # Update virtual balance logic (simplified)
            pnl_val = (current_price - entry) * amount
            self.virtual_balance += pnl_val
            
            del self.positions[symbol]
            
            return {
                'side': 'SELL',
                'symbol': symbol,
                'amount': amount,
                'reason': reason
            }
            
        return None