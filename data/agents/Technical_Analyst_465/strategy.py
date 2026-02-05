import math
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
    进化版策略 - Technical_Analyst_465 (v2.0)
    
    核心变异 (Mutation):
    1. 引入双均线系统 (EMA 7/25) 替代单一 SMA，提高趋势响应速度。
    2. 增加波动率过滤 (ATR 简化版)，避免在横盘震荡中频繁磨损。
    3. 动态仓位管理：基于当前余额的凯利公式简化版，而非固定金额。
    4. 严格风控：止损收紧至 3%，止盈采用移动止盈逻辑。
    """
    
    def __init__(self):
        # === 核心参数 ===
        self.ema_fast_window = 7
        self.ema_slow_window = 25
        self.volatility_window = 10
        
        # === 风控参数 ===
        self.stop_loss_pct = 0.03       # 3% 强制止损 (保护仅剩的本金)
        self.trailing_stop_pct = 0.05   # 回撤 5% 止盈
        self.max_position_size = 0.2    # 单笔最大仓位 20%
        self.min_trend_strength = 0.005 # 趋势强度阈值
        
        # === 状态存储 ===
        self.price_history: Dict[str, List[float]] = {}
        self.entry_prices: Dict[str, float] = {}
        self.highest_prices: Dict[str, float] = {} # 用于移动止盈
        self.positions: Dict[str, float] = {}      # 持仓数量
        
        # 初始资金 (根据当前状态更新)
        self.balance = 536.69 
        self.last_reflection = "Strategy initialized. Recovery mode activated."

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        if len(prices) < period:
            return sum(prices) / len(prices)
        
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_volatility(self, prices: List[float], period: int) -> float:
        if len(prices) < 2:
            return 0.0
        # 简化版波动率：最近N个周期的(最高-最低)/平均价
        recent = prices[-period:]
        return (max(recent) - min(recent)) / (sum(recent) / len(recent))

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策逻辑：
        1. 更新价格历史
        2. 检查持仓是否触发 止损 或 移动止盈
        3. 检查空仓是否触发 金叉买入
        """
        # 假设 prices 格式: {'BTC': {'price': 50000, ...}, ...}
        
        decision = None
        
        for symbol, data in prices.items():
            current_price = data.get('price', 0.0)
            if current_price <= 0:
                continue
                
            # 更新历史
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(current_price)
            
            # 保持历史长度适中
            if len(self.price_history[symbol]) > 50:
                self.price_history[symbol].pop(0)
            
            history = self.price_history[symbol]
            
            # === 卖出逻辑 (持仓检查) ===
            if symbol in self.positions and self.positions[symbol] > 0:
                entry_price = self.entry_prices.get(symbol, current_price)
                
                # 更新最高价用于移动止盈
                self.highest_prices[symbol] = max(self.highest_prices.get(symbol, entry_price), current_price)
                high_price = self.highest_prices[symbol]
                
                # 1. 硬止损
                pnl_pct = (current_price - entry_price) / entry_price
                if pnl_pct < -self.stop_loss_pct:
                    amount = self.positions[symbol] * current_price
                    self._close_position(symbol, current_price)
                    return TradeDecision(Signal.SELL, symbol, amount, f"Stop Loss triggered: {pnl_pct:.2%}")
                
                # 2. 移动止盈 (从最高点回撤)
                drawdown = (high_price - current_price) / high_price
                if pnl_pct > 0.02 and drawdown > self.trailing_stop_pct:
                    amount = self.positions[symbol] * current_price
                    self._close_position(symbol, current_price)
                    return TradeDecision(Signal.SELL, symbol, amount, f"Trailing Stop triggered: Profit {pnl_pct:.2%}, Drawdown {drawdown:.2%}")

            # === 买入逻辑 (仅当没有持仓且有现金时) ===
            elif self.balance > 10 and len(history) >= self.ema_slow_window:
                # 只有在没有决策时才寻找新机会
                if decision is not None:
                    continue

                ema_fast = self._calculate_ema(history, self.ema_fast_window)
                ema_slow = self._calculate_ema(history, self.ema_slow_window)
                volatility = self._calculate_volatility(history, self.volatility_window)
                
                # 趋势判断：快线 > 慢线 (金叉/多头排列)
                trend_up = ema_fast > ema_slow
                
                # 动量确认：当前价格高于快线 (避免回调接刀)
                momentum_ok = current_price > ema_fast
                
                # 波动率过滤：避免极端行情 (太高风险，太低无利可图)
                vol_ok = 0.002 < volatility < 0.05
                
                if trend_up and momentum_ok and vol_ok:
                    # 仓位计算：余额的 20%
                    trade_amount = self.balance * self.max_position_size
                    
                    # 记录模拟持仓
                    self.positions[symbol] = trade_amount / current_price
                    self.entry_prices[symbol] = current_price
                    self.highest_prices[symbol] = current_price
                    self.balance -= trade_amount
                    
                    decision = TradeDecision(
                        Signal.BUY, 
                        symbol, 
                        trade_amount, 
                        f"Trend Follow: EMA{self.ema_fast_window} > EMA{self.ema_slow_window}, Vol:{volatility:.3f}"
                    )
        
        return decision

    def _close_position(self, symbol: str, price: float):
        """内部辅助：平仓清理状态"""
        if symbol in self.positions:
            amount_usd = self.positions[symbol] * price
            self.balance += amount_usd
            del self.positions[symbol]
            if symbol in self.entry_prices: del self.entry_prices[symbol]
            if symbol in self.highest_prices: del self.highest_prices[symbol]

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """
        周期结束反思
        """
        # 计算本轮 PnL
        total_asset_value = self.balance
        # 加上持仓价值
        # 注意：实际中需要最新价格，这里简化处理，假设最后一次更新的价格
        
        self.last_reflection = (
            f"Epoch End. Balance: ${self.balance:.2f}. "
            f"Strategy shifted to EMA Trend Following with Volatility Filter. "
            f"Focusing on capital preservation (Tight Stop Loss)."
        )

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Trend is your friend, but volatility is the enemy. Filter noise with ATR."
        else:
            return "Recovering from drawdown. Adopted strict EMA crossover and 3% hard stop."