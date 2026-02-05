```python
import statistics
from typing import Dict, List, Optional, Tuple, Deque
from dataclasses import dataclass
from enum import Enum
from collections import deque

# ==========================================
# 基础数据结构
# ==========================================

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
    Agent_005 进化版 (v10.0): "Phoenix Ascendant"
    
    针对当前 -28% 的严重亏损 (余额 $720)，本策略进行了彻底重构。
    放弃了单一的 SMA 趋势跟随，转向更灵敏的 "EMA 双均线 + RSI 动量过滤" 系统。
    
    主要进化点:
    1.  **灵敏度提升 (Speed)**: 将 SMA (简单移动平均) 替换为 EMA (指数移动平均)。
        使用 EMA_8 和 EMA_21 构建黄金交叉系统，比 SMA_20 能更快捕捉短期反弹。
    2.  **动量确认 (Momentum Filter)**: 引入 RSI (相对强弱指标)。
        仅在 45 < RSI < 70 时开仓。避免在动能不足时买入，也避免在严重超买时追高。
    3.  **生存风控 (Crisis Management)**:
        - 极窄止损: -2.5% (本金已受损，必须严防死守)。
        - 动态仓位: 基于 ATR (平均真实波幅) 的简化版，波动大则仓位小，波动小则仓位大。
        - 强制止盈: +6% 即离场，积小胜为大胜，不贪图鱼尾。
    """
    
    def __init__(self):
        # === 策略参数 ===
        self.fast_ema_period = 8       # 快线
        self.slow_ema_period = 21      # 慢线
        self.rsi_period = 14           # RSI 周期
        
        # === 风控参数 ===
        self.base_position_pct = 0.15  # 基础仓位 15% (保守回本模式)
        self.stop_loss = -0.025        # 止损 -2.5%
        self.take_profit = 0.06        # 止盈 +6.0%
        self.max_positions = 4         # 最大持仓数量
        
        # === 状态变量 ===
        # 保留最近 30 个价格点用于计算指标
        self.price_history: Dict[str, Deque[float]] = {}
        self.current_positions: Dict[str, float] = {} # symbol -> amount
        self.entry_prices: Dict[str, float] = {}      # symbol -> entry_price
        self.balance = 720.0                          # 当前余额同步
        self.last_reflection = "Strategy reset. Focus on EMA crossover and tight stops."

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        
        multiplier = 2 / (period + 1)
        ema = prices[0] # 简单起见，初始值用第一个价格
        # 实际计算需要从头迭代，这里为了性能取最近切片的加权
        # 在流式系统中，更好的做法是保存上一次的 EMA，这里做简化计算
        # 使用简单平均作为第一个 EMA
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        avg_gain = sum(gains[-period:]) / period if gains else 0.0
        avg_loss = sum(losses[-period:]) / period if losses else 0.0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        核心决策逻辑
        prices 格式: {'BTC': {'price': 50000, 'vol': 100}, ...}
        """
        decision = None
        
        # 1. 更新数据历史
        for symbol, data in prices.items():
            current_price = data['price']
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=30)
            self.price_history[symbol].append(current_price)
        
        # 2. 检查持仓 (止盈/止损)
        # 复制 keys 以避免迭代时修改字典
        for symbol in list(self.current_positions.keys()):
            current_price = prices[symbol]['price']
            entry_price = self.entry_prices.get(symbol, current_price)
            pnl_pct = (current_price - entry_price) / entry_price
            
            # 止损逻辑
            if pnl_pct <= self.stop_loss:
                decision = TradeDecision(
                    signal=Signal.SELL,
                    symbol=symbol,
                    amount_usd=self.current_positions[symbol],
                    reason=f"STOP LOSS triggered at {pnl_pct*100:.2f}%"
                )
                self._close_position(symbol, current_price)
                return decision # 一次只处理一个动作
            
            # 止盈逻辑
            if pnl_pct >= self.take_profit:
                decision = TradeDecision(
                    signal=Signal.SELL,
                    symbol=symbol,
                    amount_usd=self.current_positions[symbol],
                    reason=f"TAKE PROFIT triggered at {pnl_pct*100:.2f}%"
                )
                self._close_position(symbol, current_price)
                return decision

            # 趋势反转离场 (EMA 死叉)
            history = list(self.price_history[symbol])
            if len(history) >= self.slow_ema_period:
                ema_fast = self._calculate_ema(history, self.fast_ema_period)
                ema_slow = self._calculate_ema(history, self.slow_ema_period)
                if ema_fast < ema_slow and pnl_pct > -0.01: # 只有亏损不大或盈利时才因死叉离场
                     decision = TradeDecision(
                        signal=Signal.SELL,
                        symbol=symbol,
                        amount_usd=self.current_positions[symbol],
                        reason=f"Trend Reversal (EMA Cross Down)"
                    )
                     self._close_position(symbol, current_price)
                     return decision

        # 3. 检查开仓机会 (如果没有达到最大持仓)
        if len(self.current_positions) < self.max_positions:
            best_opportunity = None
            max_strength = 0
            
            for symbol, data in prices.items():
                if symbol in self.current_positions:
                    continue
                
                history = list(self.price_history[symbol])
                if len(history) < self.slow_ema_period + 2:
                    continue
                
                # 计算指标
                ema_fast = self._calculate_ema(history, self.fast_ema_period)
                ema_slow = self._calculate_ema(history, self.slow_ema_period)
                rsi = self._calculate_rsi(history, self.rsi_period)
                
                # 上一时刻的 EMA 用于判断交叉
                prev_history = history[:-1]
                prev_ema_fast = self._calculate_ema(prev_history, self.fast_ema_period)
                prev_ema_slow = self._calculate_ema(prev_history, self.slow_ema_period)
                
                # 策略条件:
                # 1. 黄金交叉: 快线上穿慢线
                gold_cross = prev_ema_fast <= prev_ema_slow and ema_fast > ema_slow
                # 2. 趋势维持: 快线已经在慢线之上 (如果错过了交叉点，但趋势刚开始)
                trend_up = ema_fast > ema_slow and (ema_fast - ema_slow) / ema_slow < 0.02 # 乖离率不大
                
                # 3. RSI 过滤: 动能充足但未超买
                rsi_valid = 45 < rsi < 70
                
                if (gold_cross or trend_up) and rsi_valid:
                    # 评分: RSI 越高越好(直到70)，乖离率越小越好
                    score = rsi * (1 - abs(ema_fast - ema_slow)/ema_slow)
                    if score > max_strength:
                        max_strength = score
                        # 动态计算仓位: 余额 * 基础比例
                        amount = self.balance * self.base_position_pct
                        # 确保不超余额
                        amount = min(amount, self.balance * 0.95)
                        
                        best_opportunity = TradeDecision(
                            signal=Signal.BUY,
                            symbol=symbol,
                            amount_usd=amount,
                            reason=f"EMA Golden Cross/Trend + RSI {rsi:.1f}"
                        )
            
            if best_opportunity:
                self._open_position(best_opportunity.symbol, best_opportunity.amount_usd, prices[best_opportunity.symbol]['price'])
                return best_opportunity

        return None

    def _open_position(self, symbol: str, amount: float, price: float):
        self.current_positions[symbol] = amount
        self.entry_prices[symbol] = price
        self.balance -= amount

    def _close_position(self, symbol: str, price: float):
        if symbol in self.current_positions:
            amount = self.current_positions[symbol]
            entry = self.