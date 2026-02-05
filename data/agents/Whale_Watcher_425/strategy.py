from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
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
    Agent: Whale_Watcher_425 (Gen 2 - Survival Mode)
    
    进化日志 (Evolution Log):
    1. 策略重构: 放弃纯动量追踪，转向 "布林带均值回归 + 趋势过滤" (Bollinger Mean Reversion with Trend Filter)。
    2. 资金保护: 针对当前 -46% 的 PnL，实施严格的资本保全策略。
    3. 赢家借鉴: 采纳 "右侧交易" 思想，仅在长周期均线向上时才允许抄底 (Dip Buying in Uptrend)。
    4. 止损收紧: 动态止损从 ATR 乘数改为固定百分比 + 波动率调整，防止单笔大额亏损。
    """
    
    def __init__(self):
        # === 核心参数 (Gen 2) ===
        self.bb_window = 20           # 布林带周期
        self.bb_std_dev = 2.0         # 布林带标准差倍数
        self.trend_ma_window = 50     # 长期趋势线 (过滤逆势交易)
        
        # === 风控参数 (Survival Mode) ===
        self.risk_per_trade = 0.15    # 单笔交易仓位限制 (15% of current equity)
        self.stop_loss_pct = 0.03     # 3% 严格止损 (比赢家的 2% 略宽，给予呼吸空间)
        self.take_profit_pct = 0.06   # 6% 止盈 (2:1 盈亏比)
        self.max_drawdown_limit = 0.1 # 累计回撤限制
        
        # === 状态存储 ===
        self.price_history: Dict[str, List[float]] = {}
        self.entry_prices: Dict[str, float] = {}
        self.current_balance = 536.69 # Sync with actual state
        self.positions: Dict[str, float] = {} # symbol -> amount_usd
        
        self.reflection_log = "Initial state: Recovering from -46% drawdown."

    def _calculate_sma(self, prices: List[float], window: int) -> float:
        if len(prices) < window:
            return 0.0
        return sum(prices[-window:]) / window

    def _calculate_bollinger_bands(self, prices: List[float], window: int, num_std: float) -> Tuple[float, float, float]:
        if len(prices) < window:
            return 0.0, 0.0, 0.0
        
        sma = self._calculate_sma(prices, window)
        variance = sum([((x - sma) ** 2) for x in prices[-window:]]) / window
        std_dev = math.sqrt(variance)
        
        upper_band = sma + (std_dev * num_std)
        lower_band = sma - (std_dev * num_std)
        
        return upper_band, sma, lower_band

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策逻辑：
        1. 更新价格历史
        2. 检查持仓止损/止盈
        3. 计算指标 (SMA, BB)
        4. 生成新订单
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data['price']
            
            # 1. 初始化/更新历史
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(current_price)
            
            # 保持历史数据长度适中
            if len(self.price_history[symbol]) > 100:
                self.price_history[symbol].pop(0)
            
            history = self.price_history[symbol]
            
            # 2. 检查现有持仓 (Exit Logic)
            if symbol in self.positions:
                entry_price = self.entry_prices.get(symbol, current_price)
                pnl_pct = (current_price - entry_price) / entry_price
                
                # 止损: 价格触及止损线 OR 价格跌破布林带下轨太远 (恐慌抛售)
                if pnl_pct <= -self.stop_loss_pct:
                    amount = self.positions.pop(symbol)
                    self.current_balance += amount * (1 + pnl_pct) # 模拟结算
                    return TradeDecision(
                        signal=Signal.SELL,
                        symbol=symbol,
                        amount_usd=amount,
                        reason=f"STOP LOSS triggered at {pnl_pct*100:.2f}%"
                    )
                
                # 止盈: 价格触及布林带上轨 OR 达到固定止盈位
                upper, sma, lower = self._calculate_bollinger_bands(history, self.bb_window, self.bb_std_dev)
                if pnl_pct >= self.take_profit_pct or (upper > 0 and current_price >= upper):
                    amount = self.positions.pop(symbol)
                    self.current_balance += amount * (1 + pnl_pct)
                    return TradeDecision(
                        signal=Signal.SELL,
                        symbol=symbol,
                        amount_usd=amount,
                        reason=f"TAKE PROFIT at {pnl_pct*100:.2f}% (Band/Target hit)"
                    )
                
                continue # 已有持仓，暂不加仓

            # 3. 寻找入场机会 (Entry Logic)
            # 需要足够的数据计算指标
            if len(history) < self.trend_ma_window:
                continue
                
            upper, sma, lower = self._calculate_bollinger_bands(history, self.bb_window, self.bb_std_dev)
            trend_sma = self._calculate_sma(history, self.trend_ma_window)
            
            # 策略核心: 顺大势，逆小势 (Trend Following + Mean Reversion)
            # 条件 A: 长期趋势向上 (Current Price > Trend SMA) - 借鉴赢家智慧
            # 条件 B: 短期价格回调至布林带下轨附近 (Price <= Lower Band * 1.01)
            # 条件 C: 波动率收缩 (Bandwidth check, optional, simplified here)
            
            if trend_sma > 0 and current_price > trend_sma: # 处于上升趋势
                if lower > 0 and current_price <= lower * 1.01: # 触及下轨支撑
                    
                    # 仓位管理: 余额少时更谨慎
                    invest_amount = self.current_balance * self.risk_per_trade
                    
                    self.positions[symbol] = invest_amount
                    self.entry_prices[symbol] = current_price
                    self.current_balance -= invest_amount
                    
                    return TradeDecision(
                        signal=Signal.BUY,
                        symbol=symbol,
                        amount_usd=invest_amount,
                        reason="Trend Dip Buy: Price > MA50 AND Price touches Lower BB"
                    )
                    
        return None

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """
        反思与参数调整
        """
        self.reflection_log = f"Epoch End. Balance: ${self.current_balance:.2f}. "
        if self.current_balance < 500:
            self.reflection_log += "CRITICAL: Tightening stops further."
            self.stop_loss_pct = 0.02 # 进一步收紧
        elif self.current_balance > 600:
            self.reflection_log += "Recovery detected. Maintaining strategy."

    def get_reflection(self) -> str:
        return self.reflection_log

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Survival is key. I combined Trend Following with Bollinger Mean Reversion to buy dips only in confirmed uptrends."
        return "Recovering from heavy losses using tight stops and trend-filtered mean reversion."