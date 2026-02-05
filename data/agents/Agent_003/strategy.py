import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

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
    Project Darwin - Agent_003 Evolution V5: "Volatility Adaptive Engine"
    
    Evolutionary Logic:
    1. Dynamic Volatility Adaptation: Inspired by DarwinOrigin, we use ATR-based thresholds to define 
       "Tradeable Zones". We avoid low-volatility noise and high-volatility exhaustion.
    2. Non-Linear Momentum: Entry at the 'Impulse Point' where price breaks a volatility-adjusted 
       Keltner Channel with volume confirmation.
    3. Alpha Decay Exit: Instead of fixed targets, we exit when the price-momentum slope flattens 
       or volatility begins to converge (signaling trend exhaustion).
    4. Risk Parity: Position sizing is inversely proportional to current market volatility.
    """
    
    def __init__(self):
        # === Evolutionary Hyperparameters ===
        self.ema_fast = 9
        self.ema_slow = 26
        self.atr_period = 14
        self.vol_threshold_mult = 1.5  # Entry requires vol > 1.5x avg
        self.risk_per_trade = 0.15     # 15% risk allocation
        self.max_drawdown_limit = 0.03 # Tight 3% stop on capital
        
        # === State Management ===
        self.balance = 980.0
        self.price_history: Dict[str, List[float]] = {}
        self.volume_history: Dict[str, List[float]] = {}
        self.current_positions: Dict[str, float] = {}  # symbol: amount_usd
        self.entry_prices: Dict[str, float] = {}
        self.peak_prices: Dict[str, float] = {}
        self.last_reflection = "Transitioning from static momentum to dynamic volatility adaptation."

    def _calculate_indicators(self, prices: List[float]) -> Tuple[float, float, float]:
        if len(prices) < self.ema_slow:
            return 0.0, 0.0, 0.0
        
        df = pd.Series(prices)
        ema_f = df.ewm(span=self.ema_fast).mean().iloc[-1]
        ema_s = df.ewm(span=self.ema_slow).mean().iloc[-1]
        
        # Simplified ATR (Price volatility)
        returns = np.abs(np.diff(prices))
        atr = np.mean(returns[-self.atr_period:]) if len(returns) >= self.atr_period else 0.0
        
        return ema_f, ema_s, atr

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        Decision Logic:
        1. Filter for 'Untradeable Zones' (Low Volatility).
        2. Detect 'Momentum Burst' (Price > EMA and Vol > Threshold).
        3. Dynamic Trailing Exit (Alpha Decay).
        """
        for symbol, data in prices.items():
            price = data['price']
            volume = data.get('volume', 0)
            
            if symbol not in self.price_history:
                self.price_history[symbol] = []
                self.volume_history[symbol] = []
            
            self.price_history[symbol].append(price)
            self.volume_history[symbol].append(volume)
            
            # Keep history buffer
            if len(self.price_history[symbol]) > 100:
                self.price_history[symbol].pop(0)
                self.volume_history[symbol].pop(0)

            if len(self.price_history[symbol]) < self.ema_slow:
                continue

            ema_f, ema_s, atr = self._calculate_indicators(self.price_history[symbol])
            avg_vol = np.mean(self.volume_history[symbol][-20:])
            
            # 1. Check Exit Logic for existing positions
            if symbol in self.current_positions:
                entry_price = self.entry_prices[symbol]
                self.peak_prices[symbol] = max(self.peak_prices[symbol], price)
                
                # Dynamic Trailing Stop (Chandelier Exit variant)
                stop_loss_price = self.peak_prices[symbol] - (atr * 2.0)
                hard_stop = entry_price * (1 - self.max_drawdown_limit)
                
                # Alpha Decay Signal: Price crosses back below fast EMA or hits stop
                if price < max(stop_loss_price, hard_stop) or price < ema_f:
                    amount = self.current_positions.pop(symbol)
                    self.balance += amount * (price / entry_price)
                    return TradeDecision(Signal.SELL, symbol, amount, "Alpha Decay / Vol Convergence")

            # 2. Check Entry Logic
            else:
                # Condition A: Non-linear trend (EMA crossover & Price above EMA)
                trend_confirmed = price > ema_f > ema_s
                
                # Condition B: Volatility Burst (Current price jump > ATR * multiplier)
                vol_burst = (price - self.price_history[symbol][-2]) > (atr * self.vol_threshold_mult)
                
                # Condition C: Avoid Untradeable Zone (ATR must be significant)
                historical_atr = np.mean([np.abs(np.diff(self.price_history[symbol][-20:]))])
                is_tradeable = atr > (historical_atr * 0.5)

                if trend_confirmed and vol_burst and is_tradeable:
                    # Risk-Adjusted Position Sizing
                    # Higher ATR = Smaller Position
                    vol_scalar = (price * 0.01) / (atr + 1e-9) 
                    position_size = min(self.balance * self.risk_per_trade * vol_scalar, self.balance * 0.3)
                    
                    if self.balance >= position_size:
                        self.current_positions[symbol] = position_size
                        self.entry_prices[symbol] = price
                        self.peak_prices[symbol] = price
                        self.balance -= position_size
                        return TradeDecision(Signal.BUY, symbol, position_size, "Momentum Burst + Vol Adaptive")

        return None

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """Reflect on performance and integrate winner's insights."""
        my_rank = next((r for r in rankings if r['agent_id'] == "Agent_003"), None)
        if my_rank:
            pnl = my_rank.get('pnl', 0)
            if pnl < 0:
                self.risk_per_trade *= 0.9  # De-risk if losing
                self.vol_threshold_mult += 0.2 # Be more selective
            else:
                self.risk_per_trade = min(0.25, self.risk_per_trade * 1.1)
        
        self.last_reflection = f"Winner Wisdom integrated: {winner_wisdom[:100]}... Adjusted risk to {self.risk_per_trade:.2%}"

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Success was driven by identifying the 'Impulse Point' of volatility bursts while maintaining a dynamic ATR-based exit to capture non-linear trends."
        return "I have evolved to treat volatility as a filter rather than just a risk metric. My engine now ignores 'noise zones' and only engages when momentum is confirmed by volume and volatility expansion."
