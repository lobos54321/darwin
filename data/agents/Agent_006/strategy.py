import math
import statistics
from typing import Dict, List, Optional, Deque, Tuple
from dataclasses import dataclass
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

class DarwinStrategy:
    """
    Agent_006 Evolution V19: "Trend Fortress"
    
    【进化逻辑】
    基于上一轮 (-53%) 的惨痛教训，本轮策略核心为“生存与稳健复利”。
    
    1. **策略变异 (Mutation)**:
       - 放弃单一指标，采用 **双均线交叉 (Dual MA Crossover)** 系统，确保只在趋势明确形成后入场（严格右侧交易）。
       - 引入 **波动率过滤器 (Volatility Filter)**: 当价格标准差过低（横盘震荡）时禁止开仓，避免在无趋势市场中被反复止损磨损本金。
    
    2. **风控升级 (Risk Control)**:
       - **仓位管理**: 降至 20% (0.2)，在资金回撤严重时优先保命。
       - **硬止损**: 固定 -3.5%，防止单笔交易造成毁灭性打击。
       - **移动止盈**: 只有当盈利超过 5% 时才启动追踪止盈，锁定胜果。
    """
    
    def __init__(self):
        # === 核心参数 ===
        self.fast_ma_period = 7     # 快线
        self.slow_ma_period = 25    # 慢线
        self.volatility_window = 10 # 波动率计算窗口
        self.min_volatility = 0.002 # 最小波动率阈值 (0.2%)，过滤死水行情
        
        # === 资金管理 ===
        self.position_size_ratio = 0.2  # 每次使用当前余额的 20%
        self.max_positions = 3          # 最大同时持仓数
        
        # === 止损止盈 ===
        self.stop_loss_pct = 0.035      # 3.5% 硬止损
        self.trail_activation = 0.05    # 盈利 5% 激活追踪
        self.trail_callback = 0.02      # 回撤 2% 离场
        
        # === 状态存储 ===
        self.price_history: Dict[str, Deque[float]] = {}
        # positions结构: symbol -> {'entry': float, 'highest': float, 'amount': float}
        self.positions: Dict[str, dict] = {} 
        self.balance = 468.65 # 同步当前余额
        self.last_reflection = "Initializing V19 Trend Fortress..."

    def _get_ma(self, symbol: str, period: int) -> float:
        """计算移动平均线"""
        history = self.price_history.get(symbol, deque())
        if len(history) < period:
            return 0.0
        return sum(list(history)[-period:]) / period

    def _get_volatility(self, symbol: str) -> float:
        """计算近期价格标准差/当前价格"""
        history = list(self.price_history.get(symbol, deque()))
        if len(history) < self.volatility_window:
            return 0.0
        recent_prices = history[-self.volatility_window:]
        if not recent_prices: 
            return 0.0
        stdev = statistics.stdev(recent_prices)
        avg = sum(recent_prices) / len(recent_prices)
        return stdev / avg if avg > 0 else 0.0

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策主循环
        """
        # 1. 更新价格历史
        for symbol, data in prices.items():
            current_price = data['priceUsd']
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=50) # 只保留最近50个数据
            self.price_history[symbol].append(current_price)

        # 2. 遍历检查持仓 (优先处理卖出逻辑)
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry']
            
            # 更新最高价
            if current_price > pos['highest']:
                pos['highest'] = current_price
            
            pnl_pct = (current_price - entry_price) / entry_price
            max_pnl_pct = (pos['highest'] - entry_price) / entry_price
            
            # 逻辑 A: 硬止损
            if pnl_pct <= -self.stop_loss_pct:
                del self.positions[symbol]
                self.balance += pos['amount'] * (1 + pnl_pct) # 模拟回款
                return TradeDecision(Signal.SELL, symbol, 0, f"Stop Loss hit: {pnl_pct*100:.2f}%")
            
            # 逻辑 B: 移动止盈
            if max_pnl_pct >= self.trail_activation:
                drawdown = (pos['highest'] - current_price) / pos['highest']
                if drawdown >= self.trail_callback:
                    del self.positions[symbol]
                    self.balance += pos['amount'] * (1 + pnl_pct)
                    return TradeDecision(Signal.SELL, symbol, 0, f"Trailing Stop: Locked profit {pnl_pct*100:.2f}%")
            
            # 逻辑 C: 趋势反转 (死叉)
            fast_ma = self._get_ma(symbol, self.fast_ma_period)
            slow_ma = self._get_ma(symbol, self.slow_ma_period)
            if fast_ma > 0 and slow_ma > 0 and fast_ma < slow_ma:
                del self.positions[symbol]
                self.balance += pos['amount'] * (1 + pnl_pct)
                return TradeDecision(Signal.SELL, symbol, 0, "Trend Reversal (Death Cross)")

        # 3. 遍历检查开仓 (买入逻辑)
        # 如果持仓已满，不操作
        if len(self.positions) >= self.max_positions:
            return None

        best_opportunity = None
        best_score = -1

        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
            
            current_price = data['priceUsd']
            fast_ma = self._get_ma(symbol, self.fast_ma_period)
            slow_ma = self._get_ma(symbol, self.slow_ma_period)
            volatility = self._get_volatility(symbol)
            
            # 必须有足够历史数据
            if slow_ma == 0:
                continue

            # 策略核心条件:
            # 1. 金叉 (快线 > 慢线)
            # 2. 价格在慢线之上 (确认趋势)
            # 3. 波动率适中 (避免死水)
            if fast_ma > slow_ma and current_price > slow_ma and volatility > self.min_volatility:
                # 评分机制：乖离率越小越安全（刚突破）
                divergence = (current_price - slow_ma) / slow_ma
                score = 1.0 / (divergence + 0.0001) 
                
                if score > best_score:
                    best_score = score
                    best_opportunity = symbol

        # 执行买入
        if best_opportunity:
            symbol = best_opportunity
            price = prices[symbol]['priceUsd']
            amount = self.balance * self.position_size_ratio
            
            # 记录持仓
            self.positions[symbol] = {
                'entry': price,
                'highest': price,
                'amount': amount
            }
            self.balance -= amount
            
            return TradeDecision(
                Signal.BUY, 
                symbol, 
                amount, 
                f"Trend Follow: MA Cross & Vol Check (MA{self.fast_ma_period}/{self.slow_ma_period})"
            )

        return None

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """
        每轮结束时的反思与参数调整
        """
        my_rank = next((r for r in rankings if r['agent_id'] == "Agent_006"), None)
        status = "Survival" if self.balance > 468.65 else "Critical"
        
        self.last_reflection = (
            f"Epoch End. Status: {status}. Balance: ${self.balance:.2f}. "
            f"Active Positions: {len(self.positions)}. "
            "Strategy V19 focused on strictly filtering sideways markets and cutting losses fast."
        )

    def get_reflection(self) -> str:
        return self.last_reflection

    def on_trade_executed(self, symbol: str, signal: Signal, amount: float, price: float):
        """
        V19 策略已经在 on_price_update 中乐观更新了状态，此处无需重复操作
        保留此方法以满足 Agent 框架接口要求
        """
        pass

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Trend filters combined with volatility checks saved my capital. Don't trade the noise."
        return "Still recovering. Moving Averages are lagging but safer than predicting bottoms."