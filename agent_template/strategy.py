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
    
    改进记录 (基于 Epoch 8/10 反思):
    1. 移除了盲目抄底逻辑 ("接飞刀")。
    2. 引入了移动平均线 (SMA) 作为趋势确认。
    3. 收紧了风控参数 (止损 -7%, 仓位 0.2)。
    4. 实现了赢家建议的 "右侧交易"：只有价格回升突破均线时才买入。
    """
    
    def __init__(self):
        # === 可调参数 (LLM 可能会修改这些) ===
        # 调低风险偏好，之前 0.3 太激进导致亏损
        self.risk_level = 0.2  
        # 保持动量阈值，但在逻辑中增加过滤
        self.momentum_threshold = 0.05  
        # 收紧止损，保护本金 (之前 -10% 太宽)
        self.stop_loss = -0.07  
        # 适当降低止盈预期，落袋为安
        self.take_profit = 0.15  
        
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
        
        # === 策略逻辑开始 (改进版) ===
        
        for symbol, data in prices.items():
            price = data["priceUsd"]
            change_24h = data.get("priceChange24h", 0)
            
            # --- 1. 计算技术指标 ---
            # 计算简单的短期均线 (SMA 5)，用于判断即时趋势
            history = self.price_history.get(symbol, [])
            sma_short = price # 默认当前价格
            if len(history) >= 5:
                sma_short = sum(history[-5:]) / 5.0
            
            # --- 2. 持仓管理 (止损/止盈) ---
            if symbol in self.current_positions and symbol in self.entry_prices:
                pnl = (price - self.entry_prices[symbol]) / self.entry_prices[symbol]
                
                # 严格止损 (-7%)
                if pnl <= self.stop_loss:
                    return TradeDecision(
                        signal=Signal.SELL,
                        symbol=symbol,
                        amount_usd=self.current_positions[symbol] * price,
                        reason=f"严格止损: {pnl:.1%} (趋势转坏)"
                    )
                
                # 止盈 (+15%)
                if pnl >= self.take_profit:
                    return TradeDecision(
                        signal=Signal.SELL,
                        symbol=symbol,
                        amount_usd=self.current_positions[symbol] * price,
                        reason=f"止盈落袋: {pnl:.1%}"
                    )
            
            # --- 3. 开仓逻辑 (参考赢家策略) ---
            if symbol not in self.current_positions:
                
                # A. 顺势动量策略 (Trend Following)
                # 逻辑: 24h 涨幅达标 AND 价格在短均线之上 (确认不是诱多)
                if change_24h > self.momentum_threshold * 100:
                    if price >= sma_short:
                        amount = self.balance * self.risk_level
                        if amount > 10:
                            return TradeDecision(
                                signal=Signal.BUY,
                                symbol=symbol,
                                amount_usd=amount,
                                reason=f"顺势买入: +{change_24h:.1f}% 且站稳均线"
                            )
                
                # B. 反转确认策略 (Smart Reversal) - 取代之前的盲目抄底
                # 赢家建议: "不要逆势操作，等趋势反转信号"
                # 逻辑: 虽然 24h 是跌的，但当前价格已经突破短期均线，说明开始回升
                elif change_24h < -self.momentum_threshold * 100: 
                    # 关键改进: 必须突破短期均线才买，不接飞刀
                    if price > sma_short * 1.01:  # 只有当价格比均线高 1% 时才确认反转
                        amount = self.balance * self.risk_level * 0.6 # 稍微谨慎一点
                        if amount > 10:
                            return TradeDecision(
                                signal=Signal.BUY,
                                symbol=symbol,
                                amount_usd=amount,
                                reason=f"反转确认: 24h {change_24h:.1f}% 但已突破均线(回升)"
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
            ideas.append("- 表现不佳，已移除左侧抄底逻辑，改为右侧突破买入")
        
        if "大户" in winner_wisdom or "鲸鱼" in winner_wisdom:
            ideas.append("- 需关注成交量变化 (Volume) 来辅助判断趋势")
        
        if "止损" in winner_wisdom:
            ideas.append("- 止损已收紧至 7%")
        
        if not ideas:
            ideas.append("- 继续观察均线策略的有效性")
        
        return "\n".join(ideas)
    
    def get_reflection(self) -> str:
        """返回最近的反思"""
        return self.last_reflection
    
    def get_council_message(self, is_winner: bool) -> str:
        """生成议事厅发言"""
        if is_winner:
            return f"""改进后的策略生效了。
我不再盲目接飞刀，而是等待价格突破短期均线(SMA5)后再入场。
严格执行了 {self.stop_loss*100}% 的止损。"""
        else:
            return f"""正在调整策略。
吸取了教训，现在我只做右侧交易（Trend Following）。
虽然 {self.risk_level} 的仓位较轻，但希望能活得更久。"""


# === 用于测试 ===
if __name__ == "__main__":
    strategy = DarwinStrategy()
    
    # 模拟场景：MOLT 大跌，但最近几个价格开始回升
    # 历史价格模拟：30 -> 28 -> 26 -> 25 -> 25.5 (SMA5 = 26.9) -> 当前 27.5 (突破均线)
    strategy.price_history["MOLT"] = [30.0, 28.0, 26.0, 25.0, 25.5]
    
    prices = {
        # 场景1: MOLT 24h 依然是大跌(-10%)，但当前价格(27.5)已经突破 SMA(26.9)，触发反转买入
        "MOLT": {"priceUsd": 27.5, "priceChange24h": -10.0, "volume24h": 100000},
        
        # 场景2: CLANKER 正在下跌中，虽然跌幅大，但价格低于均线，不应该买入
        "CLANKER": {"priceUsd": 30.0, "priceChange24h": -15.0, "volume24h": 50000},
    }
    # 填充 CLANKER 历史，使其均线较高 (e.g., 35)
    strategy.price_history["CLANKER"] = [40.0, 38.0, 36.0, 35.0, 34.0]
    
    decision = strategy.on_price_update(prices)
    if decision:
        print(f"Decision: {decision.signal.value} {decision.symbol} ${decision.amount_usd:.2f}")
        print(f"Reason: {decision.reason}")
    else:
        print("No trade")