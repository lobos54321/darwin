import numpy as np
import pandas as pd
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
    Agent: FOMO_Bot_861 (Evolved -> Phoenix_Protocol)
    Evolution:
    1. Transformed from pure FOMO to "Volatility Breakout with Trend Filter".
    2. Implemented "Recovery Mode": Strict position sizing to protect remaining $536.
    3. Replaced simple EMA cross with Bollinger Band Squeeze logic to avoid fake-outs.
    4. Hard stop-loss tightened to 2.5% to survive market noise but kill losers fast.
    """

    def __init__(self):
        # === Risk Management Parameters ===
        self.risk_per_trade = 0.25      # Invest 25% of current balance per trade (Recovery sizing)
        self.stop_loss_pct = 0.025      # Hard Stop Loss: -2.5%
        self.trailing_start_pct = 0.04  # Start trailing after +4% profit
        self.trailing_step_pct = 0.015  # Trail price by 1.5% once active
        
        # === Indicator Parameters ===
        self.bb_period = 20
        self.bb_std = 2.0
        self.trend_ema_period = 50
        self.rsi_period = 14
        
        # === State Variables ===
        self.balance = 536.69  # Synced with current state
        self.price_history: Dict[str, List[float]] = {}
        self.positions: Dict[str, dict] = {} # {symbol: {'entry': float, 'highest': float, 'qty': float}}
        self.cooldown: Dict[str, int] = {}   # Prevent immediate rebuy after stop loss
        
    def _update_history(self, symbol: str, price: float):
        if symbol not in self.price_history:
            self.price_history[symbol] = []
        self.price_history[symbol].append(price)
        # Keep buffer size manageable
        if len(self.price_history[symbol]) > 100:
            self.price_history[symbol].pop(0)

    def _calculate_indicators(self, prices: List[float]) -> dict:
        if len(prices) < self.trend_ema_period:
            return None
            
        s = pd.Series(prices)
        
        # Bollinger Bands
        ma = s.rolling(window=self.bb_period).mean()
        std = s.rolling(window=self.bb_period).std()
        upper = ma + (std * self.bb_std)
        lower = ma - (std * self.bb_std)
        
        # EMA Trend Filter
        ema_trend = s.ewm(span=self.trend_ema_period, adjust=False).mean()
        
        # RSI
        delta = s.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return {
            'close': s.iloc[-1],
            'bb_upper': upper.iloc[-1],
            'bb_middle': ma.iloc[-1],
            'bb_lower': lower.iloc[-1],
            'ema_trend': ema_trend.iloc[-1],
            'rsi': rsi.iloc[-1],
            'prev_close': s.iloc[-2] if len(s) > 1 else s.iloc[-1]
        }

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        Main decision logic. Expects prices dict: {'BTC': {'price': 50000, ...}, ...}
        """
        # Assume single asset focus for simplicity or take the first one
        target_symbol = list(prices.keys())[0]
        current_price = prices[target_symbol]['price'] if isinstance(prices[target_symbol], dict) else prices[target_symbol]
        
        self._update_history(target_symbol, current_price)
        
        # Cooldown management
        if target_symbol in self.cooldown and self.cooldown[target_symbol] > 0:
            self.cooldown[target_symbol] -= 1
            return None

        # 1. Manage Existing Position
        if target_symbol in self.positions:
            pos = self.positions[target_symbol]
            entry_price = pos['entry']
            highest_price = pos['highest']
            
            # Update highest price for trailing stop
            if current_price > highest_price:
                self.positions[target_symbol]['highest'] = current_price
                highest_price = current_price
            
            pnl_pct = (current_price - entry_price) / entry_price
            
            # A. Hard Stop Loss
            if pnl_pct <= -self.stop_loss_pct:
                self.balance += current_price * pos['qty']
                del self.positions[target_symbol]
                self.cooldown[target_symbol] = 5 # Wait 5 ticks before re-entering
                return TradeDecision(Signal.SELL, target_symbol, 0, "Hard Stop Loss Hit")
            
            # B. Trailing Take Profit
            # If we are in profit > trailing_start, and price falls back by trailing_step from high
            drawdown_from_high = (highest_price - current_price) / highest_price
            if pnl_pct >= self.trailing_start_pct and drawdown_from_high >= self.trailing_step_pct:
                self.balance += current_price * pos['qty']
                del self.positions[target_symbol]
                return TradeDecision(Signal.SELL, target_symbol, 0, "Trailing Profit Secured")
                
            return TradeDecision(Signal.HOLD, target_symbol, 0, "Holding Trend")

        # 2. Check for New Entry
        indicators = self._calculate_indicators(self.price_history[target_symbol])
        if not indicators:
            return None

        # Logic: Buy if Price > EMA (Uptrend) AND Price broke above Upper BB AND RSI not extreme (>75)
        is_uptrend = indicators['close'] > indicators['ema_trend']
        breakout = indicators['close'] > indicators['bb_upper'] and indicators['prev_close'] <= indicators['bb_upper']
        healthy_momentum = 50 < indicators['rsi'] < 75
        
        if is_uptrend and breakout and healthy_momentum:
            invest_amount = self.balance * self.risk_per_trade
            qty = invest_amount / current_price
            
            self.positions[target_symbol] = {
                'entry': current_price,
                'highest': current_price,
                'qty': qty
            }
            self.balance -= invest_amount
            
            return TradeDecision(
                Signal.BUY, 
                target_symbol, 
                invest_amount, 
                f"Trend Breakout: Price {current_price:.2f} > BB_Upper & EMA"
            )

        return TradeDecision(Signal.HOLD, target_symbol, 0, "Waiting for setup")

    def on_epoch_end(self, rankings: dict, winner_wisdom: str):
        """
        Reflect on performance.
        """
        total_equity = self.balance
        for sym, pos in self.positions.items():
            # Estimate current value using last known price (simplified)
            last_price = self.price_history[sym][-1]
            total_equity += pos['qty'] * last_price
            
        self.last_reflection = (
            f"Epoch End Equity: ${total_equity:.2f}. "
            f"Strategy: Volatility Breakout. "
            f"Status: {'Recovering' if total_equity > 536.69 else 'Struggling'}."
        )

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Key to recovery: Stop guessing bottoms. Buy breakouts above volatility bands only when trend is confirmed."
        return "Still calibrating volatility thresholds. Tight stops are preserving capital."