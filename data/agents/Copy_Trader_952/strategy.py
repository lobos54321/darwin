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
    进化版策略 - Copy_Trader_952 (Gen 2)
    
    进化日志:
    1. 状态诊断: 初始策略导致 -46.3% 亏损，主要原因是缺乏趋势确认和风控。
    2. 核心变异: 从"盲目复制"进化为"均线趋势 + RSI 动量"混合模型。
    3. 引入 EMA (指数移动平均): 比 SMA 更快响应近期价格变化。
    4. 引入 RSI (相对强弱指标): 避免在高点买入 (RSI > 70 禁买)。
    5. 动态风控: 实施移动止损 (Trailing Stop) 以锁定利润，强制止损设为 -3%。
    """
    
    def __init__(self):
        # === 进化后的参数 ===
        self.risk_level = 0.15          # 降低单笔仓位风险，保护剩余本金
        self.ema_short_window = 7       # 短期均线
        self.ema_long_window = 21       # 长期均线
        self.rsi_window = 14            # RSI 周期
        self.rsi_overbought = 70        # 超买阈值
        self.stop_loss_pct = 0.03       # 3% 强制止损
        self.trailing_stop_activation = 0.05 # 盈利 5% 后激活移动止损
        self.trailing_callback = 0.02   # 移动止损回调 2% 触发卖出
        
        # === 状态管理 ===
        self.price_history: Dict[str, List[float]] = {}
        self.current_positions: Dict[str, float] = {}   # symbol -> amount
        self.entry_prices: Dict[str, float] = {}        # symbol -> entry_price
        self.highest_prices: Dict[str, float] = {}      # symbol -> highest_price_since_entry
        self.balance = 536.69  # 更新为当前余额
        self.last_reflection = "Initial evolution complete."

    def _calculate_ema(self, prices: List[float], window: int) -> float:
        if not prices or len(prices) < window:
            return prices[-1] if prices else 0.0
        
        multiplier = 2 / (window + 1)
        ema = statistics.mean(prices[:window]) # Simple average for first value
        
        for price in prices[window:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_rsi(self, prices: List[float], window: int = 14) -> float:
        if len(prices) < window + 1:
            return 50.0 # Default neutral
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        if len(deltas) < window:
            return 50.0

        avg_gain = sum(gains[-window:]) / window if gains else 0
        avg_loss = sum(losses[-window:]) / window if losses else 0
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策逻辑:
        1. 更新数据
        2. 检查持仓 (止损/移动止盈)
        3. 扫描机会 (EMA金叉 + RSI健康)
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data.get('price', 0.0)
            if current_price <= 0: continue
            
            # 1. 更新历史数据
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(current_price)
            # 保持历史数据长度适中，避免内存溢出
            if len(self.price_history[symbol]) > 50:
                self.price_history[symbol].pop(0)
                
            history = self.price_history[symbol]
            
            # 2. 检查现有持仓 (卖出逻辑)
            if symbol in self.current_positions:
                entry_price = self.entry_prices.get(symbol, current_price)
                highest = self.highest_prices.get(symbol, entry_price)
                
                # 更新最高价
                if current_price > highest:
                    self.highest_prices[symbol] = current_price
                    highest = current_price
                
                pnl_pct = (current_price - entry_price) / entry_price
                drawdown_from_high = (highest - current_price) / highest
                
                # A. 强制止损
                if pnl_pct <= -self.stop_loss_pct:
                    amount = self.current_positions[symbol]
                    self.balance += amount * current_price # 模拟回款
                    del self.current_positions[symbol]
                    del self.entry_prices[symbol]
                    del self.highest_prices[symbol]
                    return TradeDecision(Signal.SELL, symbol, amount, f"Stop Loss hit: {pnl_pct:.2%}")
                
                # B. 移动止盈
                if pnl_pct >= self.trailing_stop_activation and drawdown_from_high >= self.trailing_callback:
                    amount = self.current_positions[symbol]
                    self.balance += amount * current_price
                    del self.current_positions[symbol]
                    del self.entry_prices[symbol]
                    del self.highest_prices[symbol]
                    return TradeDecision(Signal.SELL, symbol, amount, f"Trailing Stop hit: High {highest:.2f}, Curr {current_price:.2f}")
                    
            # 3. 寻找买入机会 (仅当没有持仓且有余额时)
            elif self.balance > 10 and len(history) >= self.ema_long_window:
                ema_short = self._calculate_ema(history, self.ema_short_window)
                ema_long = self._calculate_ema(history, self.ema_long_window)
                rsi = self._calculate_rsi(history, self.rsi_window)
                
                # 信号: 短期均线上穿长期均线 (金叉) 且 RSI 未超买
                # 额外过滤: 当前价格必须高于 EMA Long (确认趋势)
                if ema_short > ema_long and current_price > ema_long and rsi < self.rsi_overbought:
                    # 检查是否刚刚发生金叉 (上一时刻 short <= long) - 简化处理，只看当前状态
                    
                    # 仓位管理: 使用剩余资金的 risk_level
                    invest_amount = self.balance * self.risk_level
                    # 最小交易额限制
                    if invest_amount < 10: 
                        continue
                        
                    self.balance -= invest_amount
                    self.current_positions[symbol] = invest_amount / current_price
                    self.entry_prices[symbol] = current_price
                    self.highest_prices[symbol] = current_price
                    
                    return TradeDecision(Signal.BUY, symbol, invest_amount, f"EMA Cross (S:{ema_short:.2f}>L:{ema_long:.2f}) & RSI:{rsi:.1f}")

        return None

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """每轮结束时的反思与参数微调"""
        self.last_reflection = f"Epoch end. Balance: {self.balance:.2f}. Strategy: EMA+RSI+TrailingStop."
        
        # 简单的自适应逻辑: 如果还是亏损，进一步收紧风控
        if self.balance < 536.69: # 相比上一轮
            self.risk_level = max(0.05, self.risk_level * 0.8)
            self.stop_loss_pct = 0.02 # 收紧止损
        elif self.balance > 600:
            self.risk_level = min(0.3, self.risk_level * 1.1)

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Trend following with EMA and dynamic Trailing Stop is key to recovery."
        return "Recovering from drawdown using tight risk management and RSI filters."