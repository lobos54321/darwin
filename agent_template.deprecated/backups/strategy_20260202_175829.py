"""
Darwin Agent 策略模板
⚠️ 这个文件会被 LLM 自动重写！

策略类需要实现:
- on_price_update(prices): 收到价格时的决策
- on_epoch_end(rankings, winner_wisdom): Epoch 结束时的反思
- get_reflection(): 返回本轮反思总结
"""

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
    基础策略类 - Agent 的交易大脑
    
    ⚠️ LLM 会重写这个类的方法来进化策略
    """
    
    def __init__(self):
        # === 可调参数 (LLM 可能会修改这些) ===
        self.risk_level = 0.3  # 风险偏好 (0-1)
        self.momentum_threshold = 0.05  # 动量阈值 (5%)
        self.stop_loss = -0.10  # 止损线 (-10%)
        self.take_profit = 0.20  # 止盈线 (+20%)
        
        # === 状态变量 ===
        self.price_history: Dict[str, List[float]] = {}
        self.current_positions: Dict[str, float] = {}
        self.entry_prices: Dict[str, float] = {}
        self.balance = 1000.0
        self.last_reflection = ""
    
    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        核心决策函数 - 收到价格更新时调用
        
        Args:
            prices: {"CLANKER": {"priceUsd": 35.0, "priceChange24h": 2.5, ...}, ...}
        
        Returns:
            TradeDecision 或 None (不操作)
        """
        
        # 更新价格历史
        for symbol, data in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(data["priceUsd"])
            # 只保留最近 100 个价格
            self.price_history[symbol] = self.price_history[symbol][-100:]
        
        # === 策略逻辑开始 (LLM 可能重写这部分) ===
        
        for symbol, data in prices.items():
            price = data["priceUsd"]
            change_24h = data.get("priceChange24h", 0)
            
            # 检查止损/止盈
            if symbol in self.current_positions and symbol in self.entry_prices:
                pnl = (price - self.entry_prices[symbol]) / self.entry_prices[symbol]
                
                if pnl <= self.stop_loss:
                    return TradeDecision(
                        signal=Signal.SELL,
                        symbol=symbol,
                        amount_usd=self.current_positions[symbol] * price,
                        reason=f"止损触发: {pnl:.1%}"
                    )
                
                if pnl >= self.take_profit:
                    return TradeDecision(
                        signal=Signal.SELL,
                        symbol=symbol,
                        amount_usd=self.current_positions[symbol] * price,
                        reason=f"止盈触发: {pnl:.1%}"
                    )
            
            # 动量策略: 24h 涨幅超过阈值则买入
            if change_24h > self.momentum_threshold * 100:
                if symbol not in self.current_positions:
                    amount = self.balance * self.risk_level
                    if amount > 10:  # 最小交易额
                        return TradeDecision(
                            signal=Signal.BUY,
                            symbol=symbol,
                            amount_usd=amount,
                            reason=f"动量买入: 24h +{change_24h:.1f}%"
                        )
            
            # 反转策略: 24h 跌幅过大则抄底
            if change_24h < -self.momentum_threshold * 100 * 2:
                if symbol not in self.current_positions:
                    amount = self.balance * self.risk_level * 0.5  # 谨慎抄底
                    if amount > 10:
                        return TradeDecision(
                            signal=Signal.BUY,
                            symbol=symbol,
                            amount_usd=amount,
                            reason=f"抄底买入: 24h {change_24h:.1f}%"
                        )
        
        # === 策略逻辑结束 ===
        
        return None  # 不操作
    
    def on_trade_executed(self, symbol: str, signal: Signal, amount: float, price: float):
        """交易执行后更新状态"""
        if signal == Signal.BUY:
            self.current_positions[symbol] = self.current_positions.get(symbol, 0) + amount / price
            self.entry_prices[symbol] = price
            self.balance -= amount
        elif signal == Signal.SELL:
            self.current_positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)
            self.balance += amount
    
    def on_epoch_end(self, my_rank: int, total: int, winner_wisdom: str):
        """
        Epoch 结束时调用 - 反思和学习
        
        Args:
            my_rank: 我的排名
            total: 总参赛者数
            winner_wisdom: 赢家分享的策略心得
        """
        
        # 计算表现
        performance = "优秀" if my_rank <= total * 0.1 else "中等" if my_rank <= total * 0.5 else "较差"
        
        self.last_reflection = f"""
=== Epoch 反思 ===
我的排名: {my_rank}/{total} ({performance})

赢家的分享:
{winner_wisdom}

我的当前策略:
- 风险偏好: {self.risk_level}
- 动量阈值: {self.momentum_threshold}
- 止损线: {self.stop_loss}
- 止盈线: {self.take_profit}

下一步改进方向:
{self._generate_improvement_ideas(my_rank, total, winner_wisdom)}
"""
        return self.last_reflection
    
    def _generate_improvement_ideas(self, my_rank: int, total: int, winner_wisdom: str) -> str:
        """生成改进想法"""
        ideas = []
        
        if my_rank > total * 0.5:
            ideas.append("- 表现不佳，需要参考赢家策略进行大幅调整")
        
        if "大户" in winner_wisdom or "鲸鱼" in winner_wisdom:
            ideas.append("- 考虑加入大户/鲸鱼监控逻辑")
        
        if "止损" in winner_wisdom:
            ideas.append("- 优化止损策略")
        
        if "做空" in winner_wisdom:
            ideas.append("- 考虑加入做空逻辑")
        
        if not ideas:
            ideas.append("- 继续观察，微调参数")
        
        return "\n".join(ideas)
    
    def get_reflection(self) -> str:
        """返回最近的反思"""
        return self.last_reflection
    
    def get_council_message(self, is_winner: bool) -> str:
        """生成议事厅发言"""
        if is_winner:
            return f"""这轮我的策略表现不错。
关键参数: 风险偏好={self.risk_level}, 动量阈值={self.momentum_threshold}
主要靠动量策略捕捉了上涨趋势。"""
        else:
            return f"""我需要改进。当前策略太{
                '激进' if self.risk_level > 0.5 else '保守'
            }了。
看了赢家的分享，我觉得需要调整{'止损' if self.stop_loss < -0.15 else '入场时机'}逻辑。"""


# === 用于测试 ===
if __name__ == "__main__":
    strategy = DarwinStrategy()
    
    # 模拟价格更新
    prices = {
        "CLANKER": {"priceUsd": 35.0, "priceChange24h": 8.5, "volume24h": 5000000},
        "MOLT": {"priceUsd": 0.05, "priceChange24h": -12.0, "volume24h": 100000},
    }
    
    decision = strategy.on_price_update(prices)
    if decision:
        print(f"Decision: {decision.signal.value} {decision.symbol} ${decision.amount_usd:.2f}")
        print(f"Reason: {decision.reason}")
    else:
        print("No trade")
