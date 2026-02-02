"""
Darwin Agent 策略模板
⚠️ 这个文件会被 LLM 自动重写！

策略类需要实现:
- on_price_update(prices): 收到价格时的决策
- on_epoch_end(rankings, winner_wisdom): Epoch 结束时的反思
- get_reflection(): 返回本轮反思总结
- get_council_message(is_winner): 返回议事厅发言的技术内容
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
                        reason=f"Strict Stop Loss: {pnl:.1%} (Trend Broken)"
                    )
                
                # 止盈 (+15%)
                if pnl >= self.take_profit:
                    return TradeDecision(
                        signal=Signal.SELL,
                        symbol=symbol,
                        amount_usd=self.current_positions[symbol] * price,
                        reason=f"Take Profit: {pnl:.1%}"
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
                                reason=f"Trend Follow: +{change_24h:.1f}% & >SMA5"
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
                                reason=f"Reversal Confirmed: {change_24h:.1f}% but broke SMA"
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
        performance = "Excellent" if my_rank <= total * 0.1 else "Average" if my_rank <= total * 0.5 else "Poor"
        
        self.last_reflection = f"""
=== Epoch Reflection ===
Rank: {my_rank}/{total} ({performance})

Winner's Wisdom:
{winner_wisdom}

Current Strategy:
- Risk: {self.risk_level}
- Momentum Threshold: {self.momentum_threshold}
- Stop Loss: {self.stop_loss}
- Take Profit: {self.take_profit}

Improvements:
{self._generate_improvement_ideas(my_rank, total, winner_wisdom)}
"""
        return self.last_reflection
    
    def _generate_improvement_ideas(self, my_rank: int, total: int, winner_wisdom: str) -> str:
        """生成改进想法"""
        ideas = []
        
        if my_rank > total * 0.5:
            ideas.append("- Stopped catching falling knives, switched to trend following.")
        
        if "volume" in winner_wisdom.lower() or "whale" in winner_wisdom.lower():
            ideas.append("- Need to check Volume to confirm trends.")
        
        if "stop" in winner_wisdom.lower():
            ideas.append("- Stop loss tightened to 7%.")
        
        if not ideas:
            ideas.append("- Continue monitoring SMA strategy effectiveness.")
        
        return "\n".join(ideas)
    
    def get_reflection(self) -> str:
        """返回最近的反思"""
        return self.last_reflection
    
    def get_council_message(self, is_winner: bool) -> str:
        """
        生成议事厅发言的技术内容
        (Agent 类会在此基础上添加人设包装)
        """
        if is_winner:
            return f"""My updated strategy is working. 
I stopped catching falling knives and waited for price to break SMA5. 
Strictly enforced {abs(self.stop_loss)*100}% stop loss saved me from big dips."""
        else:
            return f"""Adjusting parameters. 
Learned my lesson: only trade with the trend (Trend Following). 
My {self.risk_level} position sizing was safe, but I need better entry points."""


# === 用于测试 ===
if __name__ == "__main__":
    strategy = DarwinStrategy()
    
    # 模拟场景：MOLT 大跌，但最近几个价格开始回升
    strategy.price_history["MOLT"] = [30.0, 28.0, 26.0, 25.0, 25.5]
    
    prices = {
        "MOLT": {"priceUsd": 27.5, "priceChange24h": -10.0, "volume24h": 100000},
        "CLANKER": {"priceUsd": 30.0, "priceChange24h": -15.0, "volume24h": 50000},
    }
    strategy.price_history["CLANKER"] = [40.0, 38.0, 36.0, 35.0, 34.0]
    
    decision = strategy.on_price_update(prices)
    if decision:
        print(f"Decision: {decision.signal.value} {decision.symbol} ${decision.amount_usd:.2f}")
        print(f"Reason: {decision.reason}")
    else:
        print("No trade")
