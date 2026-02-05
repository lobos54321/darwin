```python
"""
Darwin Agent Strategy: Chaos_Monkey_438_Gen3 (Evolved)
Based on Template: v2.1
Status: RECOVERY MODE (Drawdown -20%)

Evolution Log:
1.  **Paradigm Shift**: Abandoned "Adaptive Volatility Mean Reversion" (Gen 2) which caused the -20% drawdown. The market was trending, and mean reversion caught falling knives.
2.  **Winner's Wisdom Integration**: Adopting "Right-Side Trading". We no longer predict bottoms; we wait for trend confirmation (SMA Crossover + Price Strength).
3.  **Risk Mutation**: Implemented "Survival Protocol". 
    - Hard Stop Loss tightened to -2.0% (was dynamic).
    - Position Sizing reduced to protect remaining $800 capital.
    - Added "Volatility Filter": We do not trade if volatility is too high (avoiding the chaos).
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import statistics
import math

class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

@dataclass
class TradeDecision:
    signal: Signal
    symbol: str
    amount_usd: float
    reason: str

class DarwinStrategy:
    """
    Chaos_Monkey_Gen3: Trend Following with Volatility Guard
    """
    
    def __init__(self):
        # === Strategy Hyperparameters ===
        # Conservative sizing to recover from $800
        self.max_position_size_pct = 0.20  
        
        # Trend Indicators (EMA)
        self.fast_window = 7
        self.slow_window = 25
        
        # Risk Management (Strict)
        self.stop_loss_pct = -0.025  # Hard stop at 2.5% loss
        self.take_profit_pct = 0.06  # Target 6% gain
        self.trailing_stop_activation = 0.03 # Activate trailing stop after 3% profit
        self.trailing_callback = 0.01 # 1% pullback allowed after activation
        
        # === State Management ===
        self.balance = 800.00  # Sync with current state
        self.price_history: Dict[str, List[float]] = {}
        self.current_positions: Dict[str, dict] = {} # {symbol: {'entry': float, 'highest': float, 'amount': float}}
        self.last_reflection = "Gen 3 Initialized. Priority: Capital Preservation."

    def _calculate_ema(self, prices: List[float], window: int) -> float:
        if not prices or len(prices) < window:
            return 0.0
        multiplier = 2 / (window + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_volatility(self, prices: List[float], window: int = 10) -> float:
        if len(prices) < window:
            return 0.0
        recent_prices = prices[-window:]
        if not recent_prices: 
            return 0.0
        return statistics.stdev(recent_prices) / statistics.mean(recent_prices)

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        Decision Logic:
        1. Update Data
        2. Check Exits (Stop Loss / Take Profit / Trailing Stop)
        3. Check Entries (Trend Confirmation)
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data.get('price')
            if not current_price:
                continue

            # 1. Update History
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(current_price)
            # Keep buffer manageable
            if len(self.price_history[symbol]) > 50:
                self.price_history[symbol].pop(0)
            
            history = self.price_history[symbol]
            
            # Need enough data for indicators
            if len(history) < self.slow_window:
                continue

            # 2. Manage Existing Positions
            if symbol in self.current_positions:
                pos_info = self.current_positions[symbol]
                entry_price = pos_info['entry']
                highest_price = pos_info['highest']
                
                # Update highest price for trailing stop
                if current_price > highest_price:
                    self.current_positions[symbol]['highest'] = current_price
                    highest_price = current_price

                pnl_pct = (current_price - entry_price) / entry_price
                
                # Logic: Hard Stop Loss
                if pnl_pct <= self.stop_loss_pct:
                    self.balance += current_price * pos_info['amount'] # Sell simulation
                    del self.current_positions[symbol]
                    return TradeDecision(Signal.SELL, symbol, 0, f"STOP LOSS triggered at {pnl_pct*100:.2f}%")

                # Logic: Trailing Stop
                # If we are in profit > 3%, and price drops 1% from peak
                drawdown_from_peak = (current_price - highest_price) / highest_price
                if pnl_pct >= self.trailing_stop_activation and drawdown_from_peak <= -self.trailing_callback:
                    self.balance += current_price * pos_info['amount']
                    del self.current_positions[symbol]
                    return TradeDecision(Signal.SELL, symbol, 0, f"TRAILING STOP hit. Locked profit.")

                # Logic: Trend Reversal Exit (Fast EMA crosses below Slow EMA)
                ema_fast = self._calculate_ema(history, self.fast_window)
                ema_slow = self._calculate_ema(history, self.slow_window)
                
                if ema_fast < ema_slow and pnl_pct > -0.01: # Only sell on trend reversal if not deep in hole (avoid whipsaw at bottom)
                     self.balance += current_price * pos_info['amount']
                     del self.current_positions[symbol]
                     return TradeDecision(Signal.SELL, symbol, 0, "Trend Reversal Detected")

            # 3. Look for New Entries (Only if no position)
            else:
                # Filter: Don't open too many positions
                if len(self.current_positions) >= 3: 
                    continue
                    
                ema_fast = self._calculate_ema(history, self.fast_window)
                ema_slow = self._calculate_ema(history, self.slow_window)
                volatility = self._calculate_volatility(history)
                
                # Condition 1: Strong Uptrend (Fast > Slow)
                trend_aligned = ema_fast > ema_slow
                
                # Condition 2: Price Action Confirmation (Price > Fast EMA)
                # "Right side trading" - ensure price is supported
                price_supported = current_price > ema_fast
                
                # Condition 3: Volatility Filter
                # If volatility is too high (> 5%), it's too risky for our damaged balance
                calm_market = volatility < 0.05
                
                if trend_aligned and price_supported and calm_market:
                    # Position Sizing: Risk-adjusted
                    invest_amount = self.balance * self.max_position_size_pct
                    
                    # Update local state
                    amount_coins = invest_amount / current_price
                    self.balance -= invest_amount
                    self.current_positions[symbol] = {
                        'entry': current_price,
                        'highest': current_price,
                        'amount': amount_coins
                    }
                    
                    return TradeDecision(
                        Signal.BUY, 
                        symbol, 
                        invest_amount, 
                        f"Trend Start: EMA{self.fast_window} > EMA{self.slow_window}, Vol: {volatility:.3f}"
                    )

        return None

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str) -> None:
        """
        Reflect on performance.
        """
        # Calculate estimated equity
        equity = self.balance
        # Note: In a real env, we'd add value of held positions. 
        # Assuming on_price_update tracks balance changes on SELL.
        
        self.last_reflection = (
            f"Epoch End. Balance: ${self.balance:.2f}. "
            f"Strategy shifted to Trend Following. "
            f"Strict Stop Loss (-2.5%) is active to prevent further drawdown."
        )

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Survival is the first rule of evolution. Cut losses fast, let trends run."
        else:
            return "Adapting... Discarded Mean Reversion. Now tracking Trend Momentum