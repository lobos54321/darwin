```python
import numpy as np
import pandas as pd
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
    Agent: Copy_Trader_225 (Gen 3 - Evolved)
    Strategy: Phoenix Trend Surfer (Conservative Breakout)
    
    进化日志 (Gen 2 -> Gen 3):
    1. 修正错误: 放弃了复杂的 "均值回归 + 逆势抄底" 逻辑，该逻辑导致了 20% 的回撤。
    2. 吸收智慧: 采纳 "右侧交易" 原则，仅在趋势明确形成后入场。
    3. 核心变异: 引入 Donchian Channel (唐奇安通道) 突破作为入场信号，结合 ATR 波动率进行动态仓位管理。
    4. 风控升级: 针对当前 $800 的低余额，采用 "极度防御" 模式。硬止损收紧至 3%，并使用 EMA 动态追踪止损。
    """
    
    def __init__(self):
        # === 核心参数 ===
        self.lookback_period = 30      # 数据回溯窗口
        self.ema_fast = 10             # 快速均线 (用于追踪止损)
        self.ema_trend = 50            # 趋势均线 (用于过滤)
        self.breakout_window = 20      # 唐奇安通道周期
        self.atr_period = 14           # 波动率周期
        
        # === 风控参数 ===
        self.max_risk_per_trade = 0.02 # 单笔交易最大风险 (本金的 2%)
        self.hard_stop_loss = 0.03     # 硬止损 (3%)
        self.trailing_stop_gap = 2.0   # 追踪止损宽度 (ATR 倍数)
        
        # === 状态管理 ===
        self.balance = 800.00          # 当前余额 (已更新)
        self.initial_capital = 1000.00
        self.price_history: Dict[str, List[float]] = {}
        self.high_history: Dict[str, List[float]] = {}
        self.low_history: Dict[str, List[float]] = {}
        
        # 仓位记录: symbol -> {entry_price, size, highest_price}
        self.positions: Dict[str, dict] = {} 

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        接收价格更新 (格式: {'BTC': {'price': 50000, 'high': ..., 'low': ...}})
        """
        # 1. 更新数据历史
        for symbol, data in prices.items():
            current_price = data.get('price', data.get('close'))
            high_price = data.get('high', current_price)
            low_price = data.get('low', current_price)
            
            if symbol not in self.price_history:
                self.price_history[symbol] = []
                self.high_history[symbol] = []
                self.low_history[symbol] = []
            
            self.price_history[symbol].append(current_price)
            self.high_history[symbol].append(high_price)
            self.low_history[symbol].append(low_price)
            
            # 保持窗口大小
            if len(self.price_history[symbol]) > self.lookback_period + 10:
                self.price_history[symbol].pop(0)
                self.high_history[symbol].pop(0)
                self.low_history[symbol].pop(0)

        # 2. 遍历资产进行决策 (假设单资产或多资产)
        for symbol in prices.keys():
            return self._analyze_symbol(symbol, prices[symbol]['price'])
            
        return None

    def _analyze_symbol(self, symbol: str, current_price: float) -> Optional[TradeDecision]:
        history = self.price_history[symbol]
        
        # 数据不足时不操作
        if len(history) < self.ema_trend:
            return None

        # 计算技术指标
        series = pd.Series(history)
        ema_fast = series.ewm(span=self.ema_fast, adjust=False).mean().iloc[-1]
        ema_trend = series.ewm(span=self.ema_trend, adjust=False).mean().iloc[-1]
        
        highs = pd.Series(self.high_history[symbol])
        lows = pd.Series(self.low_history[symbol])
        
        # 唐奇安通道上轨 (过去 N 天最高价，不包含今天)
        donchian_high = highs.iloc[-(self.breakout_window+1):-1].max()
        
        # ATR 计算 (简化版)
        tr = highs - lows
        atr = tr.rolling(window=self.atr_period).mean().iloc[-1]
        if np.isnan(atr) or atr == 0:
            atr = current_price * 0.02 # 默认波动率

        # === 卖出逻辑 (止损/止盈) ===
        if symbol in self.positions:
            pos = self.positions[symbol]
            entry_price = pos['entry_price']
            pos['highest_price'] = max(pos['highest_price'], current_price)
            
            # 1. 硬止损 (保护本金的核心)
            pnl_pct = (current_price - entry_price) / entry_price
            if pnl_pct <= -self.hard_stop_loss:
                del self.positions[symbol]
                return TradeDecision(Signal.SELL, symbol, pos['size'], f"Hard Stop Loss hit: {pnl_pct:.2%}")
            
            # 2. 趋势追踪止损 (价格跌破 EMA_FAST 或 吊灯止损)
            trailing_stop_price = pos['highest_price'] - (atr * self.trailing_stop_gap)
            
            # 如果价格跌破快速均线 且 跌破追踪止损位 -> 离场
            if current_price < ema_fast and current_price < trailing_stop_price:
                reason = "Trend Weakness (EMA Cross)" if current_price < ema_fast else "Trailing Stop"
                del self.positions[symbol]
                return TradeDecision(Signal.SELL, symbol, pos['size'], f"Exit: {reason}")
                
            return TradeDecision(Signal.HOLD, symbol, 0, "Holding Trend")

        # === 买入逻辑 (突破 + 趋势过滤) ===
        else:
            # 1. 趋势过滤: 价格必须在长期均线之上 (右侧交易)
            is_uptrend = current_price > ema_trend
            
            # 2. 突破信号: 价格突破唐奇安通道上轨
            is_breakout = current_price > donchian_high
            
            # 3. 波动率过滤: 避免在极端波动时入场
            volatility_ok = atr < (current_price * 0.05) # 波动率不超过 5%
            
            if is_uptrend and is_breakout and volatility_ok:
                # 仓位管理: 基于 ATR 的风险平价
                # 愿意损失的金额 = 当前余额 * 单笔风险 (e.g., 800 * 0.02 = $16)
                # 止损距离 = 2 * ATR
                # 仓位大小 = 愿意损失金额 / 止损距离
                risk_amount = self.balance * self.max_risk_per_trade
                stop_distance = 2 * atr
                position_size_usd = risk_amount / (stop_distance / current_price)
                
                # 限制最大仓位不超过余额的 40% (防止单一资产风险过大)
                position_size_usd = min(position_size_usd, self.balance * 0.4)
                
                # 确保最小交易额
                if position_size_usd < 10: 
                    return None

                self.positions[symbol] = {
                    'entry_price': current_price,
                    'size': position_size_usd,
                    'highest_price': current_price
                }
                return TradeDecision(Signal.BUY, symbol, position_size_usd, "Donchian Breakout + Trend Confirmed")

        return None

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """
        Epoch 结束时的反思与参数调整
        """
        # 计算本轮 PnL
        current_equity = self.balance # 简化计算
        for symbol, pos in self.positions.items():
            # 假设能在最后价格平仓计算净值
            pass 
            
        # 简单的自适应逻辑: 如果亏损，进一步收紧风控
        if current_equity < self.balance:
            self.max_risk_per_trade *= 0.9 # 降低风险敞口
