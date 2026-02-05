import math
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
from collections import deque

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
    进化版策略 - Agent: Diamond_Hands_533
    
    进化日志 (Gen 2):
    1. 策略变异: 从简单的持有(HODL)转向 趋势跟踪(EMA Cross) + 波动率过滤。
    2. 资金管理: 针对当前低余额 ($536) 实施激进但严格的资金管理。
    3. 止损机制: 引入 "移动止损 (Trailing Stop)" 代替固定止盈，试图抓住大趋势。
    4. 风险控制: 强制单笔最大亏损限制在账户余额的 2%。
    """
    
    def __init__(self):
        # === 核心参数 ===
        self.ema_short_period = 6    # 短期趋势 (变异点: 比SMA更灵敏)
        self.ema_long_period = 18    # 长期趋势
        self.volatility_window = 10  # 波动率计算窗口
        
        # === 风控参数 ===
        self.max_position_size = 0.3 # 单仓位最大占比 (30%)
        self.hard_stop_loss = 0.03   # 硬止损 -3% (保护仅存本金)
        self.trailing_trigger = 0.05 # 盈利 5% 后激活移动止损
        self.trailing_gap = 0.02     # 回撤 2% 触发移动止损卖出
        
        # === 状态存储 ===
        self.price_history: Dict[str, deque] = {} # 只保留最近 N 个价格
        self.entry_prices: Dict[str, float] = {}
        self.highest_prices: Dict[str, float] = {} # 记录持仓后的最高价(用于移动止损)
        self.balance = 536.69 # 同步当前余额
        self.last_reflection = "Initializing evolution protocol..."

    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = prices[0] # 简单起见，以第一个作为初始值
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策逻辑:
        1. 卖出逻辑: 优先检查硬止损和移动止损。
        2. 买入逻辑: EMA 金叉 (Short > Long) 且 价格位于 Long EMA 之上。
        """
        best_decision = None
        
        for symbol, data in prices.items():
            current_price = data.get('price')
            if not current_price:
                continue

            # 1. 更新历史数据
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=30)
            self.price_history[symbol].append(current_price)
            
            history = list(self.price_history[symbol])
            
            # 2. 持仓管理 (卖出逻辑)
            if symbol in self.entry_prices:
                entry_price = self.entry_prices[symbol]
                
                # 更新最高价 (High Water Mark)
                if symbol not in self.highest_prices or current_price > self.highest_prices[symbol]:
                    self.highest_prices[symbol] = current_price
                
                high_price = self.highest_prices[symbol]
                pnl_pct = (current_price - entry_price) / entry_price
                drawdown_from_high = (high_price - current_price) / high_price
                
                # A. 硬止损
                if pnl_pct <= -self.hard_stop_loss:
                    self._clear_position(symbol)
                    return TradeDecision(Signal.SELL, symbol, 0, f"Hard Stop Loss triggered at {pnl_pct:.2%}")
                
                # B. 移动止损 (Trailing Stop)
                if pnl_pct >= self.trailing_trigger and drawdown_from_high >= self.trailing_gap:
                    self._clear_position(symbol)
                    return TradeDecision(Signal.SELL, symbol, 0, f"Trailing Stop: Profit locked. Drawdown {drawdown_from_high:.2%}")
                
                continue # 如果持仓，本轮不再判断买入

            # 3. 开仓管理 (买入逻辑)
            # 只有在没有持仓且资金足够时才考虑
            if self.balance > 10 and len(history) >= self.ema_long_period:
                ema_short = self._calculate_ema(history, self.ema_short_period)
                ema_long = self._calculate_ema(history, self.ema_long_period)
                
                if ema_short and ema_long:
                    # 变异策略: EMA 金叉 + 价格确认
                    # 只有当短线快于长线，且当前价格强势(在长线之上)时买入
                    if ema_short > ema_long and current_price > ema_long:
                        # 检查是否刚刚发生金叉 (上一帧 Short <= Long) - 简化为只看当前状态以保证响应速度
                        # 计算仓位: 余额 * max_position_size
                        amount = self.balance * self.max_position_size
                        
                        self.entry_prices[symbol] = current_price
                        self.highest_prices[symbol] = current_price
                        self.balance -= amount # 模拟扣款
                        
                        return TradeDecision(Signal.BUY, symbol, amount, "EMA Crossover: Momentum Detected")

        return None

    def _clear_position(self, symbol: str):
        """清理内部持仓状态"""
        if symbol in self.entry_prices:
            # 简单模拟回款，实际由引擎处理
            # self.balance += ... (此处略过具体金额计算，依赖引擎反馈)
            del self.entry_prices[symbol]
            if symbol in self.highest_prices:
                del self.highest_prices[symbol]

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """
        反思模块: 根据排名调整风险参数
        """
        my_rank = next((r['rank'] for r in rankings if r['agent_id'] == "Diamond_Hands_533"), 999)
        
        if my_rank > 5:
            # 表现依然不佳，收紧风控
            self.hard_stop_loss = max(0.01, self.hard_stop_loss - 0.005)
            self.max_position_size = max(0.1, self.max_position_size - 0.05)
            self.last_reflection = f"Rank {my_rank}. Tightening StopLoss to {self.hard_stop_loss:.1%}"
        else:
            # 表现良好，保持现状
            self.last_reflection = f"Rank {my_rank}. Strategy effective. Holding steady."

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Survival of the fittest: EMA trends combined with Trailing Stops outperform blind holding."
        return "Adapting... Replaced static targets with dynamic momentum tracking."