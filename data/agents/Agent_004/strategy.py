```python
import math
import statistics
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from collections import deque

# === 基础数据结构 ===

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
    Agent_004 Gen 8: "Phoenix Protocol" (凤凰协议)
    
    进化日志 (Gen 8 Evolution Log):
    1.  **反脆弱风控 (Anti-Fragile Risk)**:
        - 鉴于当前回撤 -15%，首要任务是保本。
        - 引入 "时间止损" (Time-based Exit): 如果持仓 8 个周期仍未盈利，强制平仓，避免资金占用。
        - 仓位计算基于当前余额 (Mark-to-Market)，而非初始本金。
    
    2.  **策略变异: 均线回归 + 动量确认 (Mean Reversion + Momentum)**:
        - 吸收赢家智慧: 使用 SMA 作为趋势基准。
        - 独特变异: 不在均线交叉时买入，而是在价格回踩均线并反弹时买入 (Pullback Entry)。
        - 逻辑: Price > SMA_Long (趋势向上) AND Price < SMA_Short (短期回调) -> 等待 Price > Prev_Close (反转确认)。
    
    3.  **动态波动率调整**:
        - 使用标准差 (StdDev) 动态调整止盈止损宽度，而不是固定百分比。
    """
    
    def __init__(self):
        # === 核心参数 ===
        self.sma_long_period = 20    # 长期趋势线
        self.sma_short_period = 5    # 短期参考线
        self.history_size = 30       # 数据缓存大小
        
        # === 风控参数 ===
        self.base_risk_per_trade = 0.02  # 单笔交易风险 (2% of Equity)
        self.max_drawdown_limit = 0.80   # 账户总熔断线 (80% of initial)
        self.time_stop_limit = 8         # 8个周期不涨就跑
        
        # === 状态管理 ===
        self.price_history: Dict[str, deque] = {}
        self.balance = 850.20  # 同步当前余额
        self.positions: Dict[str, dict] = {} # {symbol: {'entry_price': float, 'amount': float, 'entry_time': int, 'highest_price': float}}
        self.tick_counter = 0
        self.last_reflection = "Gen 8 initialized. Recovery mode active."

    def _update_history(self, prices: Dict[str, dict]):
        """更新价格历史"""
        self.tick_counter += 1
        for symbol, data in prices.items():
            price = data['price']
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.history_size)
            self.price_history[symbol].append(price)

    def _calculate_indicators(self, symbol: str) -> dict:
        """计算技术指标"""
        history = list(self.price_history[symbol])
        if len(history) < self.sma_long_period:
            return None
            
        current_price = history[-1]
        prev_price = history[-2]
        
        sma_long = statistics.mean(history[-self.sma_long_period:])
        sma_short = statistics.mean(history[-self.sma_short_period:])
        
        # 计算标准差用于动态风控
        std_dev = statistics.stdev(history[-self.sma_long_period:])
        
        return {
            "price": current_price,
            "prev_price": prev_price,
            "sma_long": sma_long,
            "sma_short": sma_short,
            "std_dev": std_dev
        }

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """核心交易逻辑"""
        self._update_history(prices)
        
        # 1. 检查持仓 (止盈/止损/时间止损)
        for symbol, pos_info in list(self.positions.items()):
            current_price = prices[symbol]['price']
            entry_price = pos_info['entry_price']
            holding_ticks = self.tick_counter - pos_info['entry_time']
            
            # 更新最高价用于移动止损
            if current_price > pos_info['highest_price']:
                self.positions[symbol]['highest_price'] = current_price
            
            pnl_pct = (current_price - entry_price) / entry_price
            
            # A. 硬止损 (吸收赢家建议: 收紧止损)
            if pnl_pct < -0.02: # -2% 坚决止损
                return self._close_position(symbol, current_price, "Hard Stop Loss (-2%)")
            
            # B. 移动止盈 (Trailing Stop)
            # 如果盈利曾超过 3%，回撤 1% 就走
            highest_gain = (pos_info['highest_price'] - entry_price) / entry_price
            if highest_gain > 0.03:
                drawdown_from_high = (pos_info['highest_price'] - current_price) / pos_info['highest_price']
                if drawdown_from_high > 0.01:
                    return self._close_position(symbol, current_price, "Trailing Stop Hit")
            
            # C. 目标止盈
            if pnl_pct > 0.06: # 6% 止盈
                return self._close_position(symbol, current_price, "Target Profit (+6%)")
                
            # D. 时间止损 (僵尸仓位清理)
            if holding_ticks >= self.time_stop_limit and pnl_pct < 0.005:
                return self._close_position(symbol, current_price, "Time Stop (Stagnant)")

        # 2. 寻找开仓机会 (仅当没有持仓或持仓未满时)
        if len(self.positions) >= 3:
            return None
            
        best_opportunity = None
        max_score = -1
        
        for symbol in prices.keys():
            if symbol in self.positions:
                continue
                
            indicators = self._calculate_indicators(symbol)
            if not indicators:
                continue
                
            # === 策略核心: 趋势中的回调 (Trend Pullback) ===
            # 1. 长期趋势向上
            trend_condition = indicators['price'] > indicators['sma_long']
            
            # 2. 短期处于回调状态 (价格低于短均线，或者刚突破短均线)
            # 这里我们寻找 "右侧入场": 价格刚从下方穿过 Short SMA
            crossover_condition = (indicators['prev_price'] < indicators['sma_short']) and \
                                  (indicators['price'] > indicators['sma_short'])
            
            # 3. 波动率过滤 (避免死水)
            volatility_ok = indicators['std_dev'] > (indicators['price'] * 0.002)
            
            if trend_condition and crossover_condition and volatility_ok:
                # 评分机制: 离长均线越近越安全 (Risk/Reward 更好)
                dist_to_long_sma = (indicators['price'] - indicators['sma_long']) / indicators['price']
                score = 1.0 - dist_to_long_sma # 距离越小分数越高
                
                if score > max_score:
                    max_score = score
                    best_opportunity = symbol

        # 执行开仓
        if best_opportunity:
            # 资金管理: 使用当前余额的 20% 开仓
            trade_amount = self.balance * 0.20
            # 确保不低于 $10
            if trade_amount < 10:
                return None
                
            price = prices[best_opportunity]['price']
            self.positions[best_opportunity] = {
                'entry_price': price,
                'amount': trade_amount,
                'entry_time': self.tick_counter,
                'highest_price': price
            }
            self.balance -= trade_amount
            
            return TradeDecision(
                signal=Signal.BUY,
                symbol=best_opportunity,
                amount_usd=trade_amount,
                reason=f"Trend Pullback: SMA Cross above {self.sma_short_period} in Uptrend"
            )

        return None

    def _close_position(self, symbol: str, price: float, reason: str) -> TradeDecision:
        """平仓辅助函数"""
        pos = self.positions.pop(symbol)
        amount = pos['amount']
        # 模拟回款 (