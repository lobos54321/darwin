"""
Darwin Agent 策略代码 - Paper_Hands_111 (Evolved to Diamond_Hands_v1)
进化方向: 趋势跟踪 + 动量过滤 + 动态止盈
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import math
import statistics

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
    进化后的策略:
    1. 趋势识别: 使用 EMA (指数移动平均) 代替 SMA，对近期价格更敏感。
    2. 动量过滤: 引入 RSI 指标，避免在超买区追高。
    3. 资金管理: 基于当前余额的动态仓位，不再全仓梭哈。
    4. 止盈止损: 引入移动止盈 (Trailing Stop) 保护利润。
    """
    
    def __init__(self):
        # === 进化后的参数 ===
        self.ema_period = 12          # 趋势判断周期
        self.rsi_period = 14          # 动量判断周期
        self.rsi_overbought = 70      # 超买阈值 (不买)
        self.rsi_oversold = 30        # 超卖阈值 (关注)
        
        # 风控参数
        self.position_size_ratio = 0.2  # 每次交易只使用 20% 资金 (生存第一)
        self.stop_loss_pct = 0.03       # 3% 硬止损 (收紧风控)
        self.trailing_start_pct = 0.05  # 盈利 5% 后开启移动止盈
        self.trailing_callback_pct = 0.02 # 回撤 2% 触发移动止盈
        
        # === 状态变量 ===
        self.price_history: Dict[str, List[float]] = {}
        self.entry_prices: Dict[str, float] = {}
        self.high_water_marks: Dict[str, float] = {} # 记录持仓后的最高价(用于移动止盈)
        self.balance = 536.69 # 初始同步当前余额
        self.last_reflection = "初始化完成，准备从亏损中恢复。"

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        multiplier = 2 / (period + 1)
        ema = prices[0] # 简单起见，初始值用第一个价格
        # 重新计算序列以获得准确的当前EMA
        # 在实际高频中应保存上一次EMA，这里为了无状态恢复重新计算
        sma = sum(prices[:period]) / period
        ema = sma
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_rsi(self, prices: List[float], period: int) -> float:
        if len(prices) < period + 1:
            return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        # 简单平均计算 (也可进化为 Wilder's Smoothing)
        avg_gain = sum(gains[-period:]) / period if gains else 0
        avg_loss = sum(losses[-period:]) / period if losses else 0.0001
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策逻辑: 
        1. 更新数据
        2. 检查持仓 (止损/移动止盈)
        3. 扫描机会 (EMA突破 + RSI健康)
        """
        target_symbol = "BTC" # 假设主要交易 BTC，也可遍历
        current_price = prices.get(target_symbol, {}).get("price", 0)
        
        if current_price == 0:
            return None

        # 1. 更新历史数据
        if target_symbol not in self.price_history:
            self.price_history[target_symbol] = []
        self.price_history[target_symbol].append(current_price)
        # 保持历史数据长度适中
        if len(self.price_history[target_symbol]) > 50:
            self.price_history[target_symbol].pop(0)
            
        history = self.price_history[target_symbol]
        
        # 2. 持仓管理 (卖出逻辑)
        if target_symbol in self.entry_prices:
            entry_price = self.entry_prices[target_symbol]
            highest_price = self.high_water_marks.get(target_symbol, entry_price)
            
            # 更新最高水位
            if current_price > highest_price:
                self.high_water_marks[target_symbol] = current_price
                highest_price = current_price
            
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown_from_high = (highest_price - current_price) / highest_price
            
            # A. 硬止损
            if pnl_pct < -self.stop_loss_pct:
                del self.entry_prices[target_symbol]
                del self.high_water_marks[target_symbol]
                return TradeDecision(Signal.SELL, target_symbol, 0, f"硬止损触发: {pnl_pct:.2%}")
            
            # B. 移动止盈
            if pnl_pct > self.trailing_start_pct and drawdown_from_high > self.trailing_callback_pct:
                del self.entry_prices[target_symbol]
                del self.high_water_marks[target_symbol]
                return TradeDecision(Signal.SELL, target_symbol, 0, f"移动止盈触发: 回撤 {drawdown_from_high:.2%}")
                
            return TradeDecision(Signal.HOLD, target_symbol, 0, "持仓观望")

        # 3. 开仓逻辑 (买入逻辑)
        # 需要足够的数据计算指标
        if len(history) < self.rsi_period + 2:
            return None
            
        ema = self._calculate_ema(history, self.ema_period)
        rsi = self._calculate_rsi(history, self.rsi_period)
        
        # 策略核心变异: 
        # 价格在 EMA 之上 (趋势向上) 且 RSI 未超买 (还有上涨空间)
        # 且 价格没有偏离 EMA 太远 (避免乖离率过大)
        deviation = (current_price - ema) / ema
        
        if current_price > ema and rsi < self.rsi_overbought and deviation < 0.05:
            amount = self.balance * self.position_size_ratio
            self.entry_prices[target_symbol] = current_price
            self.high_water_marks[target_symbol] = current_price
            return TradeDecision(Signal.BUY, target_symbol, amount, f"趋势跟随: Price>EMA({self.ema_period}), RSI={rsi:.1f}")
            
        return TradeDecision(Signal.HOLD, target_symbol, 0, "等待机会")

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """
        每轮结束时的自我反省
        """
        # 简单的反思逻辑，实际应用中会基于排名调整参数
        self.last_reflection = (
            f"本轮结束。当前策略: EMA趋势+RSI过滤+移动止盈。"
            f"重点在于保护本金({self.balance:.2f})，避免大幅回撤。"
        )

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "不要试图预测顶部，让利润奔跑，但要带好移动止盈。"
        else:
            return "Paper_Hands 已死，Diamond_Hands 重生。活下来比什么都重要。"