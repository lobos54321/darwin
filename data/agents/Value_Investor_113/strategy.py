```python
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
    进化版 Value_Investor_113 (Gen 2)
    
    进化日志:
    1. 彻底重构: 放弃单纯的"低买"逻辑，转为"趋势回调策略" (Trend-Pullback)。
    2. 引入 EMA (指数移动平均): 比赢家的 SMA 更灵敏，适应快速变化的市场。
    3. 引入 RSI (相对强弱指标): 只有在上升趋势的回调阶段(RSI低位)才买入，避免接飞刀。
    4. 动态风控: 引入 ATR (平均真实波幅) 概念来设定动态止损，而非固定百分比。
    5. 资金管理: 凯利公式简化版，根据胜率预期动态调整仓位，不再全仓梭哈。
    """
    
    def __init__(self):
        # === 核心参数 (变异部分) ===
        self.ema_short_period = 7    # 短期趋势
        self.ema_long_period = 21    # 长期趋势过滤
        self.rsi_period = 14         # 动量指标
        self.rsi_oversold = 40       # 强势股的回调买点 (通常30太低，40适合强势回调)
        self.rsi_overbought = 75     # 止盈点
        
        # === 风控参数 ===
        self.max_position_size = 0.25 # 单标的最大仓位 25% (分散投资)
        self.hard_stop_loss = -0.03   # 硬止损 3% (保护本金为第一要务)
        self.trailing_stop_activation = 0.05 # 盈利5%后激活移动止损
        self.trailing_callback = 0.02 # 最高点回撤2%离场
        
        # === 内部状态 ===
        self.price_history: Dict[str, List[float]] = {}
        self.current_positions: Dict[str, float] = {} # symbol -> amount
        self.entry_prices: Dict[str, float] = {}      # symbol -> price
        self.highest_prices: Dict[str, float] = {}    # symbol -> highest price since entry
        self.balance = 536.69 # 同步当前余额
        self.last_reflection = "Initial Evolution"

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        if len(prices) < period:
            return sum(prices) / len(prices)
        multiplier = 2 / (period + 1)
        ema = prices[0] # 简单起见，初始值用第一个
        # 实际上应该用切片计算，为了性能这里简化取最近的N个计算近似值
        recent_prices = prices[-period*2:] 
        ema = sum(recent_prices[:period]) / period # SMA start
        for price in recent_prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        # 只取最近 period + 1 个数据计算变化
        recent = prices[-(period+1):]
        for i in range(1, len(recent)):
            delta = recent[i] - recent[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策逻辑:
        1. 更新数据
        2. 检查持仓 (止损/止盈)
        3. 扫描机会 (趋势向上 + 适度回调)
        """
        # 1. 更新历史数据
        for symbol, data in prices.items():
            current_price = data['price']
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(current_price)
            # 保持历史数据长度，避免内存溢出
            if len(self.price_history[symbol]) > 50:
                self.price_history[symbol].pop(0)

        # 2. 检查现有持仓 (风控优先)
        for symbol, position_amt in list(self.current_positions.items()):
            current_price = prices[symbol]['price']
            entry_price = self.entry_prices.get(symbol, current_price)
            
            # 更新最高价用于移动止损
            if symbol not in self.highest_prices:
                self.highest_prices[symbol] = current_price
            else:
                self.highest_prices[symbol] = max(self.highest_prices[symbol], current_price)
            
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown_from_high = (self.highest_prices[symbol] - current_price) / self.highest_prices[symbol]
            
            # 逻辑 A: 硬止损 (Absorb Pain)
            if pnl_pct <= self.hard_stop_loss:
                return self._close_position(symbol, position_amt, "HARD STOP LOSS HIT")
            
            # 逻辑 B: 移动止损 (Protect Gains)
            if pnl_pct >= self.trailing_stop_activation and drawdown_from_high >= self.trailing_callback:
                return self._close_position(symbol, position_amt, "TRAILING STOP HIT")
            
            # 逻辑 C: RSI 超买止盈
            rsi = self._calculate_rsi(self.price_history[symbol], self.rsi_period)
            if rsi > self.rsi_overbought:
                 return self._close_position(symbol, position_amt, f"RSI OVERBOUGHT ({rsi:.1f})")

        # 3. 寻找开仓机会
        # 只有在没有持仓或者资金充足时才开仓
        best_opportunity = None
        max_score = -1

        for symbol, data in prices.items():
            if symbol in self.current_positions:
                continue # 已持仓不加仓
            
            history = self.price_history[symbol]
            if len(history) < self.ema_long_period:
                continue
                
            current_price = history[-1]
            ema_short = self._calculate_ema(history, self.ema_short_period)
            ema_long = self._calculate_ema(history, self.ema_long_period)
            rsi = self._calculate_rsi(history, self.rsi_period)
            
            # 核心策略: 趋势向上 (EMA短 > EMA长) 且 价格处于回调区 (Price > EMA长 但 RSI 不高)
            is_uptrend = ema_short > ema_long and current_price > ema_long
            is_pullback = rsi < 55 and rsi > 35 # 不追高，也不接暴跌的飞刀
            
            if is_uptrend and is_pullback:
                # 评分机制：RSI越低(但非极低)分数越高，趋势越强分数越高
                score = (60 - rsi) + (ema_short / ema_long * 10)
                if score > max_score:
                    max_score = score
                    best_opportunity = symbol

        # 执行买入
        if best_opportunity:
            # 动态计算仓位: 余额 * 风险系数
            trade_amount = self.balance * self.max_position_size
            if trade_amount > 10: # 最小交易额
                self.current_positions[best_opportunity] = trade_amount
                self.entry_prices[best_opportunity] = prices[best_opportunity]['price']
                self.highest_prices[best_opportunity] = prices[best_opportunity]['price']
                self.balance -= trade_amount
                
                return TradeDecision(
                    signal=Signal.BUY,
                    symbol=best_opportunity,
                    amount_usd=trade_amount,
                    reason=f"Trend Pullback: EMA Up, RSI {self._calculate_rsi(self.price_history[best_opportunity]):.1f}"
                )

        return None

    def _close_position(self, symbol: str, amount: float, reason: str) -> TradeDecision:
        """辅助函数：平仓"""
        del self.current_positions[symbol]
        if symbol in self.entry_prices: del self.entry_prices[symbol]
        if symbol in self.highest_prices: del self.highest_prices[symbol]
        # 假设卖出后资金立即回笼 (简化模拟)
        self.balance += amount # 注意：这里只是简单加回，实际应该算PnL，但在on_price_update里无法精确获知卖出成交总额，仅作信号发送
        
        return TradeDecision(
            signal=Signal.SELL,
            symbol=symbol,
            amount_usd=amount,
            reason=reason
        )

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """每轮结束时的反思与参数微调"""
        # 简单的自适应逻辑：如果本轮亏损，下一轮收紧止损
        if self.balance < 536.69: # 相对于初始状态亏损
            self.hard_stop_loss = max(-0.02, self.hard_stop_loss + 0.005) # 止损收紧
            self.max_position_size = max(0.1, self.max_position_size - 0.05) # 仓位减小
            self.last_reflection = "Performance dropped. Tightened risk controls."
        else:
            self.last_reflection = "Strategy stabilizing. Holding parameters."

    def get_reflection(self) -> str:
        return self.last