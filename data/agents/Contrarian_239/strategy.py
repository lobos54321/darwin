import math
import statistics
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
    Agent: Contrarian_239 (Evolution V2)
    
    进化日志:
    1. 修正致命缺陷: 之前的纯逆势策略在单边行情中遭遇惨败 (PnL -46%)。
    2. 策略变异 -> "智能均值回归 (Smart Mean Reversion)": 
       不再盲目接飞刀，而是寻找上升趋势中的回调 (Dip) 或下降趋势中的反弹 (Rally)。
    3. 引入 RSI (14) 指标识别超买超卖。
    4. 引入 EMA (20) 判断主趋势。
    5. 极度严格的风控: 针对当前本金腰斩的情况，实行 "生存模式"。
    """
    
    def __init__(self):
        # === 进化后的参数 ===
        self.risk_factor = 0.15      # 降低仓位，单笔最大 15% (生存优先)
        self.rsi_period = 14         # 标准 RSI 周期
        self.rsi_oversold = 35       # 超卖阈值 (买入回调)
        self.rsi_overbought = 65     # 超买阈值 (卖出获利)
        self.ema_period = 20         # 趋势基准线
        
        self.stop_loss_pct = 0.03    # 止损收紧至 3%
        self.take_profit_pct = 0.06  # 盈亏比 1:2
        
        # === 内部状态 ===
        self.price_history: Dict[str, List[float]] = {}
        self.entry_prices: Dict[str, float] = {}
        self.holdings: Dict[str, float] = {} # symbol -> quantity
        self.balance = 536.69  # 更新为当前余额
        self.initial_balance = 1000.0
        self.last_reflection = "Reborn from ashes. Trend + Reversion hybrid."

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        avg_gain = sum(gains[-period:]) / period if gains else 0
        avg_loss = sum(losses[-period:]) / period if losses else 0.0001
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_ema(self, prices: List[float], period: int = 20) -> float:
        if not prices:
            return 0.0
        if len(prices) < period:
            return statistics.mean(prices)
            
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策逻辑:
        1. 止损/止盈检查 (最高优先级)
        2. 趋势过滤器: 价格 > EMA (只做多) 或 价格 < EMA (只做空/观望)
        3. 逆势入场: 在上升趋势中 RSI 低于阈值时买入 (Buy the Dip)
        """
        best_opportunity = None
        max_score = -1.0

        for symbol, data in prices.items():
            current_price = data['price']
            
            # 0. 更新历史数据
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(current_price)
            # 保持历史长度适中
            if len(self.price_history[symbol]) > 50:
                self.price_history[symbol].pop(0)
                
            history = self.price_history[symbol]
            
            # 1. 现有持仓管理 (止损/止盈)
            if symbol in self.entry_prices:
                entry_price = self.entry_prices[symbol]
                pnl_pct = (current_price - entry_price) / entry_price
                
                # 触发硬止损
                if pnl_pct <= -self.stop_loss_pct:
                    self._close_position(symbol)
                    return TradeDecision(
                        Signal.SELL, symbol, 0, 
                        f"STOP LOSS triggered at {pnl_pct*100:.2f}%"
                    )
                
                # 触发止盈 (RSI 辅助判断)
                rsi = self._calculate_rsi(history, self.rsi_period)
                if pnl_pct >= self.take_profit_pct or (pnl_pct > 0.02 and rsi > self.rsi_overbought):
                    self._close_position(symbol)
                    return TradeDecision(
                        Signal.SELL, symbol, 0, 
                        f"TAKE PROFIT at {pnl_pct*100:.2f}% (RSI: {rsi:.1f})"
                    )
                
                continue # 持仓中，且未触发平仓，跳过开仓逻辑

            # 2. 寻找开仓机会 (仅当没有持仓该币种时)
            if len(history) < self.ema_period:
                continue

            ema = self._calculate_ema(history, self.ema_period)
            rsi = self._calculate_rsi(history, self.rsi_period)
            
            # 策略核心: 趋势跟随中的逆势入场 (Trend Pullback)
            # 条件 A: 长期趋势向上 (Price > EMA)
            # 条件 B: 短期超卖 (RSI < Threshold)
            # 条件 C: 资金允许
            
            is_uptrend = current_price > ema
            is_oversold = rsi < self.rsi_oversold
            
            if is_uptrend and is_oversold:
                # 评分机制: RSI 越低，EMA 支撑越近，分数越高
                score = (100 - rsi) + (1.0 - abs(current_price - ema)/ema * 100)
                if score > max_score:
                    max_score = score
                    amount = self.balance * self.risk_factor
                    best_opportunity = TradeDecision(
                        Signal.BUY, symbol, amount, 
                        f"Trend Pullback: Price({current_price:.2f}) > EMA({ema:.2f}) & RSI({rsi:.1f}) < {self.rsi_oversold}"
                    )

        # 执行最佳机会
        if best_opportunity:
            self.entry_prices[best_opportunity.symbol] = prices[best_opportunity.symbol]['price']
            # 简单的余额扣除模拟
            self.balance -= best_opportunity.amount_usd
            return best_opportunity

        return None

    def _close_position(self, symbol: str):
        if symbol in self.entry_prices:
            # 假设全仓卖出
            del self.entry_prices[symbol]
            # 实际回款逻辑应由交易所引擎处理，这里仅重置策略状态
            # 为简化，假设回款逻辑在外部，这里只负责发信号

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """
        周期结束反思
        """
        self.last_reflection = (
            f"Epoch End. Balance: {self.balance:.2f}. "
            f"Strategy shifted from blind contrarian to 'Pullback Sniper'. "
            f"Stricter risk control ({self.stop_loss_pct*100}%) active."
        )

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Buy when the crowd is fearful, but only if the trend is your friend."
        else:
            return "Adapting... Moving from catching knives to catching tennis balls."