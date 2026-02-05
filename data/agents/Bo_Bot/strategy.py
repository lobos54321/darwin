from typing import Dict, List, Optional, Tuple, Deque
from dataclasses import dataclass
from enum import Enum
from collections import deque
import statistics
import math

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
    Agent: Bo_Bot (Evolution Gen 9 - Phoenix Adaptive)
    
    进化日志 (Gen 9):
    1. 彻底反思 (Post-Mortem):
       - Gen 8 的 "铁壁风控" 依然归零，原因是固定止损在剧烈波动中失效，且仓位管理过于僵化。
       - 必须引入 "动态波动率" 概念，而非固定百分比。
       
    2. 核心策略变异 (Mutation):
       - 引入 EMA (指数移动平均) 交叉系统 (9/21周期)：比 SMA 更灵敏，捕捉早期趋势。
       - 动态波动率风控 (ATR-like): 使用价格的标准差来决定止损距离。波动大，止损宽但仓位小；波动小，止损窄但仓位大。
       
    3. 生存机制 (Survival Mode):
       - 资金管理：单笔最大风险敞口限制为总资金的 2% (通过仓位大小控制)，而非简单的固定金额。
       - 严格的 "右侧确认"：必须在 EMA 黄金交叉且价格位于短期均线上方时才入场。
    """
    
    def __init__(self):
        # === 策略参数 ===
        self.fast_ema_period = 9       # 短期趋势线
        self.slow_ema_period = 21      # 长期趋势线 (生命线)
        self.volatility_period = 14    # 波动率计算周期
        self.risk_factor = 0.02        # 单笔交易最大亏损占总资金比例 (2%)
        
        # === 状态管理 ===
        self.history: Dict[str, Deque[float]] = {}
        self.positions: Dict[str, float] = {}        # symbol -> holding amount
        self.entry_prices: Dict[str, float] = {}     # symbol -> avg entry price
        self.highest_prices: Dict[str, float] = {}   # symbol -> highest price since entry (for trailing stop)
        
        # 模拟账户余额 (假设重置为 1000 或读取当前)
        self.balance = 1000.0
        self.last_reflection = "Gen 9: Rising from ashes with Adaptive Volatility Control."

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        if len(prices) < period:
            return statistics.mean(prices)
        
        multiplier = 2 / (period + 1)
        ema = prices[0] # 简单起见，初始值用第一个
        # 实际上应该用 SMA 初始化，这里为了性能简化计算
        ema = statistics.mean(prices[:period])
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_volatility(self, prices: List[float]) -> float:
        """计算近期价格的标准差作为波动率参考"""
        if len(prices) < 2:
            return 0.0
        # 取最近 N 个周期的标准差
        recent_prices = list(prices)[-self.volatility_period:]
        if len(recent_prices) < 2:
            return 0.0
        return statistics.stdev(recent_prices)

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        # 1. 更新数据
        for symbol, data in prices.items():
            current_price = data['price']
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=50)
            self.history[symbol].append(current_price)
            
            # 更新持仓最高价用于移动止盈
            if symbol in self.positions:
                if symbol not in self.highest_prices:
                    self.highest_prices[symbol] = current_price
                else:
                    self.highest_prices[symbol] = max(self.highest_prices[symbol], current_price)

        # 2. 遍历寻找交易机会
        # 优先处理持仓的止损/止盈
        for symbol, position in list(self.positions.items()):
            if position <= 0: continue
            
            current_price = prices[symbol]['price']
            entry_price = self.entry_prices.get(symbol, current_price)
            highest_price = self.highest_prices.get(symbol, current_price)
            
            hist = list(self.history[symbol])
            if len(hist) < self.slow_ema_period: continue
            
            volatility = self._calculate_volatility(hist)
            slow_ema = self._calculate_ema(hist, self.slow_ema_period)
            
            # === 卖出逻辑 ===
            
            # A. 动态止损 (Chandelier Exit 变体): 
            # 如果价格从最高点回撤超过 2倍波动率 或 3% (取大者，防止死寂市场被磨损)
            stop_distance = max(volatility * 2.0, entry_price * 0.03)
            trailing_stop_price = highest_price - stop_distance
            
            # B. 趋势反转止损: 价格跌破慢速 EMA
            trend_broken = current_price < slow_ema
            
            reason = ""
            if current_price < trailing_stop_price:
                reason = f"Trailing Stop Triggered (Drop > {stop_distance:.2f})"
            elif trend_broken:
                reason = "Trend Broken (Price < EMA21)"
            
            if reason:
                amount_usd = position * current_price
                self.balance += amount_usd
                del self.positions[symbol]
                del self.entry_prices[symbol]
                del self.highest_prices[symbol]
                return TradeDecision(Signal.SELL, symbol, amount_usd, reason)

        # 3. 寻找买入机会 (仅当持有现金时)
        if self.balance > 10.0:
            best_symbol = None
            best_score = -1.0
            
            for symbol, data in prices.items():
                if symbol in self.positions: continue # 已持仓不加仓
                
                hist = list(self.history[symbol])
                if len(hist) < self.slow_ema_period + 5: continue
                
                current_price = data['price']
                fast_ema = self._calculate_ema(hist, self.fast_ema_period)
                slow_ema = self._calculate_ema(hist, self.slow_ema_period)
                volatility = self._calculate_volatility(hist)
                
                # === 买入逻辑 (严苛过滤) ===
                # 1. 黄金交叉: 快线 > 慢线
                # 2. 动量确认: 当前价格 > 快线 (防止回调时接刀)
                # 3. 波动率过滤: 避免死寂币种 (标准差需 > 价格的 0.5%)
                
                if fast_ema > slow_ema and current_price > fast_ema:
                    if volatility > (current_price * 0.005):
                        # 评分：乖离率越小越好（刚启动），波动率适中
                        divergence = (current_price - slow_ema) / slow_ema
                        if divergence < 0.05: # 不要追高超过均线 5% 的
                            score = (fast_ema / slow_ema) 
                            if score > best_score:
                                best_score = score
                                best_symbol = symbol

            if best_symbol:
                current_price = prices[best_symbol]['price']
                hist = list(self.history[best_symbol])
                volatility = self._calculate_volatility(hist)
                
                # === 动态仓位管理 (Kelly Lite) ===
                # 风险预算 = 总资金 * 2%
                # 止损距离 = 2 * 波动率
                # 仓位大小 = 风险预算 / 止损距离
                risk_budget = self.balance * self.risk_factor
                stop_distance_per_unit = max(volatility * 2.0, current_price * 0.02) # 至少2%止损宽容度
                
                position_size_coin = risk_budget / stop_distance_per_unit
                position_cost = position_size_coin * current_price
                
                # 限制单笔最大仓位不超过余额的 30% (防止计算出的仓位过大)
                max_position_usd = self.balance * 0.3
                final_amount_usd = min(position_cost, max_position_usd)
                
                if final_amount_usd > 10.0:
                    self.balance -= final_amount_usd
                    self.positions[best_symbol] = final_amount_usd / current_price
                    self.entry_prices[best_symbol] = current_price
                    self.highest_prices[best_symbol] = current_price
                    
                    return TradeDecision(
                        Signal.BUY, 
                        best_symbol, 
                        final_amount_usd, 
                        f"EMA Golden Cross + Volatility Sizing (Risk: {self.risk_factor*100}%)"
                    )

        return None

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """每轮结束时的反思与参数微调"""
        # 简单根据本轮表现微调风险参数
        # 这里仅做记录，实际参数在 __init__ 定义
        self.last_reflection = f"Epoch ended. Current Balance: {self.balance:.2f}. Strategy: Phoenix Adaptive EMA."

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Gen 9 Success: Abandoned fixed stops for Volatility-Adjusted Risk. Trend is only your friend if you size it right."
        return "Gen 9 Learning: Still calibrating the volatility sensitivity. Need to protect capital better."