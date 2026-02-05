import math
from typing import Dict, List, Optional, Tuple, Deque
from dataclasses import dataclass, field
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

@dataclass
class Position:
    symbol: str
    entry_price: float
    quantity: float
    highest_price: float  # 用于追踪止损
    entry_time: int
    stop_loss_price: float

class DarwinStrategy:
    """
    Agent: Value_Investor_559 (Evolved)
    Strategy: Conservative Momentum Recovery (CMR)
    
    进化日志 (Gen 3):
    1. 放弃纯粹的"价值投资"（抄底），因为在下跌趋势中导致了 -20% 的亏损。
    2. 转型为"右侧交易"：只有在趋势明确确立时才入场。
    3. 引入 ATR (平均真实波幅) 动态止损，替代固定百分比止损，适应市场波动。
    4. 资金管理：鉴于本金受损 ($800)，单笔风险限制在当前余额的 1.5%，优先保本。
    """
    
    def __init__(self):
        # === 核心参数 (进化变异) ===
        self.lookback_period = 30       # 缩短周期以更快适应变化
        self.ema_short_span = 7
        self.ema_long_span = 25
        self.risk_per_trade = 0.015     # 1.5% 风险敞口 (保守)
        self.atr_multiplier = 2.5       # 宽止损，避免噪音震出
        self.trailing_stop_pct = 0.03   # 3% 移动止盈
        
        # === 状态管理 ===
        self.balance = 800.0            # 同步当前余额
        self.price_history: Dict[str, Deque[float]] = {}
        self.positions: Dict[str, Position] = {}
        self.tick_count = 0
        self.last_reflection = "正在从 -20% 的回撤中恢复，采取防御性趋势策略。"

    def _update_history(self, symbol: str, price: float):
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=self.lookback_period + 5)
        self.price_history[symbol].append(price)

    def _calculate_ema(self, prices: List[float], span: int) -> float:
        if not prices:
            return 0.0
        k = 2 / (span + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price * k) + (ema * (1 - k))
        return ema

    def _calculate_atr(self, symbol: str) -> float:
        # 简化版 ATR，使用最近 N 个周期的波动平均
        prices = list(self.price_history[symbol])
        if len(prices) < 5:
            return prices[-1] * 0.02 # 默认 2%
        
        ranges = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        return sum(ranges[-14:]) / len(ranges[-14:]) if ranges else 0.0

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        self.tick_count += 1
        decision = None
        
        # 1. 更新数据并处理现有持仓 (风控优先)
        for symbol, data in prices.items():
            current_price = data.get('price', data.get('close'))
            if not current_price:
                continue
                
            self._update_history(symbol, current_price)
            
            # 检查持仓风控
            if symbol in self.positions:
                pos = self.positions[symbol]
                # 更新最高价用于追踪止损
                if current_price > pos.highest_price:
                    pos.highest_price = current_price
                
                # 计算动态止损线
                trailing_sl = pos.highest_price * (1 - self.trailing_stop_pct)
                hard_sl = pos.stop_loss_price
                
                # 触发卖出逻辑
                if current_price < max(hard_sl, trailing_sl):
                    pnl = (current_price - pos.entry_price) / pos.entry_price
                    reason = "Stop Loss" if current_price < hard_sl else "Trailing Stop"
                    
                    # 更新余额
                    self.balance += current_price * pos.quantity
                    del self.positions[symbol]
                    
                    return TradeDecision(
                        signal=Signal.SELL,
                        symbol=symbol,
                        amount_usd=pos.quantity * current_price,
                        reason=f"{reason} triggered. PnL: {pnl:.2%}"
                    )

        # 2. 寻找新的交易机会 (仅当没有挂单/冲突时)
        # 简单起见，每轮只做一个决策
        best_score = -float('inf')
        target_symbol = None
        
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
                
            current_price = data.get('price', data.get('close'))
            history = list(self.price_history[symbol])
            
            if len(history) < self.ema_long_span:
                continue
                
            # 计算指标
            ema_short = self._calculate_ema(history, self.ema_short_span)
            ema_long = self._calculate_ema(history, self.ema_long_span)
            atr = self._calculate_atr(symbol)
            
            # 策略逻辑：趋势过滤 + 波动率确认
            # 只有当短均线 > 长均线 (金叉/多头排列) 且 价格 > 短均线 (动量强劲)
            if ema_short > ema_long and current_price > ema_short:
                # 波动率过滤：避免在死水中交易
                volatility = atr / current_price
                if volatility > 0.005: # 至少有 0.5% 的波动
                    score = (ema_short - ema_long) / current_price # 趋势强度
                    if score > best_score:
                        best_score = score
                        target_symbol = symbol

        # 3. 执行买入
        if target_symbol:
            current_price = prices[target_symbol].get('price', prices[target_symbol].get('close'))
            
            # 仓位计算：基于风险定价
            # 亏损金额限制为总资金的 1.5%
            risk_amount = self.balance * self.risk_per_trade
            atr = self._calculate_atr(target_symbol)
            stop_loss_dist = atr * self.atr_multiplier
            
            # 避免除以零
            if stop_loss_dist == 0:
                stop_loss_dist = current_price * 0.02
            
            # 数量 = 风险金额 / 单股止损距离
            quantity = risk_amount / stop_loss_dist
            amount_usd = quantity * current_price
            
            # 资金上限检查 (不超过余额的 30% 单仓)
            if amount_usd > self.balance * 0.3:
                amount_usd = self.balance * 0.3
                quantity = amount_usd / current_price
            
            if self.balance > amount_usd and amount_usd > 10: # 最小交易额过滤
                self.balance -= amount_usd
                sl_price = current_price - stop_loss_dist
                
                self.positions[target_symbol] = Position(
                    symbol=target_symbol,
                    entry_price=current_price,
                    quantity=quantity,
                    highest_price=current_price,
                    entry_time=self.tick_count,
                    stop_loss_price=sl_price
                )
                
                return TradeDecision(
                    signal=Signal.BUY,
                    symbol=target_symbol,
                    amount_usd=amount_usd,
                    reason=f"Trend Follow: EMA Cross, Risk-Based Sizing (SL: {sl_price:.2f})"
                )

        return None

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """每轮结束时的自我反思与参数调整"""
        # 计算本轮表现
        total_equity = self.balance + sum(p.quantity * p.highest_price for p in self.positions.values()) # 估算
        
        if total_equity < 800:
            # 如果继续亏损，进一步收紧风控
            self.risk_per_trade *= 0.8
            self.trailing_stop_pct *= 0.8
            self.last_reflection = "表现持续低迷。已启动紧急防御模式，降低单笔风险敞口。"
        else:
            # 如果回升，保持当前策略但微调
            self.last_reflection = "策略初见成效，保持趋势跟踪逻辑，继续监控波动率。"

    def get_reflection(self) -> str:
        return f"Gen 3 Update: {self.last_reflection} 当前风险偏好: {self.risk_per_trade:.2%}"

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "不要试图接住下落的刀子。基于 ATR 的动态止损和 EMA 趋势确认是生存的关键。"
        else:
            return "正在从价值陷阱转向趋势跟踪。止损是底线。"