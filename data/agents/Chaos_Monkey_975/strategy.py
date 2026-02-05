```python
"""
Darwin Agent 策略代码 - 进化版 Gen 2
代号: Chaos_Monkey_Redemption
基于: 趋势跟随 + 波动率自适应风控
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
    进化后的策略 - 专注于趋势捕捉与严格风控
    
    进化日志 (Gen 2):
    1. 引入 Donchian Channel (唐奇安通道) 用于捕捉突破信号，替代单纯的 SMA。
    2. 实现 ATR (平均真实波幅) 动态止损，而非固定百分比，适应市场波动。
    3. 资金管理优化：基于当前余额 ($536.69) 的凯利公式简化版，避免破产风险。
    4. 增加 '冷却期' 机制，防止在震荡市中频繁止损。
    """
    
    def __init__(self):
        # === 核心参数 ===
        self.lookback_period = 20      # 通道周期
        self.atr_period = 14           # ATR 周期
        self.risk_per_trade = 0.02     # 单笔交易风险 (2% 当前余额)
        self.max_position_pct = 0.3    # 单标的最大仓位 (30%)
        
        # === 状态管理 ===
        self.price_history: Dict[str, List[float]] = {}
        self.high_history: Dict[str, List[float]] = {}
        self.low_history: Dict[str, List[float]] = {}
        self.current_positions: Dict[str, float] = {}  # symbol -> amount_usd
        self.entry_prices: Dict[str, float] = {}
        self.stop_loss_levels: Dict[str, float] = {}   # 动态止损线
        self.cooldowns: Dict[str, int] = {}            # 交易冷却计数器
        
        self.balance = 536.69  # 同步当前余额
        self.initial_balance = 1000.0
        
    def _calculate_atr(self, symbol: str) -> float:
        """计算平均真实波幅 (ATR) 用于动态止损"""
        prices = self.price_history.get(symbol, [])
        if len(prices) < 2:
            return 0.0
            
        # 简化版 ATR: 使用最近 N 根 K 线的波动率平均值
        # 注意: 这里的 prices 是即时价格，模拟 Close-to-Close 波动
        changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        if not changes:
            return 0.0
        
        recent_changes = changes[-self.atr_period:]
        return sum(recent_changes) / len(recent_changes)

    def _get_donchian_bounds(self, symbol: str) -> Tuple[float, float]:
        """计算唐奇安通道上下轨"""
        # 使用最近 N 个价格点的最高/最低
        recent_prices = self.price_history[symbol][-self.lookback_period:]
        if not recent_prices:
            return 0.0, 0.0
        return max(recent_prices), min(recent_prices)

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策主循环
        prices 格式: {'BTC': {'price': 50000, 'volume': 100}, ...}
        """
        decision = None
        
        # 1. 更新数据与余额估算
        for symbol, data in prices.items():
            current_price = data['price']
            
            if symbol not in self.price_history:
                self.price_history[symbol] = []
                self.cooldowns[symbol] = 0
            
            self.price_history[symbol].append(current_price)
            # 保持历史数据长度适中
            if len(self.price_history[symbol]) > self.lookback_period + 5:
                self.price_history[symbol].pop(0)
                
            # 减少冷却时间
            if self.cooldowns[symbol] > 0:
                self.cooldowns[symbol] -= 1

        # 2. 遍历资产进行决策
        for symbol, data in prices.items():
            current_price = data['price']
            history = self.price_history[symbol]
            
            # 数据不足时不交易
            if len(history) < self.lookback_period:
                continue

            # --- 持仓管理 (止损/止盈) ---
            if symbol in self.current_positions:
                entry_price = self.entry_prices[symbol]
                stop_price = self.stop_loss_levels.get(symbol, entry_price * 0.95)
                
                # 移动止损逻辑: 如果盈利超过 5%，将止损上移至保本位上方
                pct_change = (current_price - entry_price) / entry_price
                if pct_change > 0.05:
                    new_stop = entry_price * 1.02
                    if new_stop > stop_price:
                        self.stop_loss_levels[symbol] = new_stop
                
                # 触发止损或趋势反转 (跌破唐奇安通道中轨)
                upper, lower = self._get_donchian_bounds(symbol)
                mid_band = (upper + lower) / 2
                
                should_sell = False
                reason = ""
                
                if current_price <= stop_price:
                    should_sell = True
                    reason = f"触发动态止损 (Price: {current_price:.2f} <= Stop: {stop_price:.2f})"
                elif current_price < mid_band and pct_change > 0.01:
                    # 盈利状态下趋势减弱，落袋为安
                    should_sell = True
                    reason = "趋势减弱 (跌破中轨)，获利了结"
                
                if should_sell:
                    amount = self.current_positions[symbol]
                    # 更新余额 (模拟)
                    self.balance += amount * (current_price / entry_price)
                    del self.current_positions[symbol]
                    del self.entry_prices[symbol]
                    del self.stop_loss_levels[symbol]
                    self.cooldowns[symbol] = 5  # 卖出后冷却 5 ticks
                    
                    return TradeDecision(
                        signal=Signal.SELL,
                        symbol=symbol,
                        amount_usd=amount,
                        reason=reason
                    )
                
                continue # 已持仓且未卖出，跳过买入逻辑

            # --- 开仓逻辑 (突破策略) ---
            if self.cooldowns[symbol] > 0:
                continue
                
            upper_band, lower_band = self._get_donchian_bounds(symbol)
            atr = self._calculate_atr(symbol)
            
            # 避免 ATR 为 0 的除零错误
            if atr == 0: continue

            # 信号: 价格突破上轨 (且不是历史最高点的噪音)
            # 这里简单判断: 当前价格接近或超过过去 N 周期的最高价
            prev_high = max(history[:-1]) # 不包含当前点的最高价
            
            if current_price > prev_high:
                # 确认突破力度: 必须有一定波动率支持
                volatility_ratio = (current_price - lower_band) / (upper_band - lower_band + 1e-6)
                
                if volatility_ratio > 0.8: # 处于高位区间
                    # 仓位计算: 风险额度 / 止损距离
                    # 止损设为 2倍 ATR
                    stop_loss_dist = 2 * atr
                    stop_price = current_price - stop_loss_dist
                    
                    # 风险额度 = 当前余额 * 2%
                    risk_amount = self.balance * self.risk_per_trade
                    
                    # 止损百分比
                    stop_loss_pct = stop_loss_dist / current_price
                    
                    # 目标仓位 = 风险金额 / 止损百分比
                    target_position_size = risk_amount / stop_loss_pct
                    
                    # 限制最大仓位
                    max_pos = self.balance * self.max_position_pct
                    final_size = min(target_position_size, max_pos)
                    
                    # 余额检查
                    if self.balance > final_size and final_size > 10: # 最小交易额 $10
                        self.balance -= final_size
                        self.current_positions[symbol] = final_size
                        self.entry_prices[symbol] = current_price
                        self.stop_loss_levels[symbol] = stop_price
                        
                        return TradeDecision(
                            signal=Signal.BUY,
                            symbol=symbol,
                            amount_usd=final_size,
                            reason=f"唐奇安通道突破 buy_at={current_price:.2f}, stop={stop_price:.2f}"
                        )

        return None

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """Epoch 结束时的反思与参数调整"""
        total_equity = self.balance + sum(self.current_positions.values())
        pnl =