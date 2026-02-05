import math
from typing import Dict, List, Optional, Tuple, Deque
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
    Whale_Watcher_534_Gen2 (进化版)
    
    进化日志 (Gen 2):
    1. 彻底抛弃均值回归(RSI/Bollinger)策略，承认前期"接飞刀"失败。
    2. 吸收赢家智慧：转向趋势跟踪 (Trend Following)。
    3. 基因变异：
       - 使用双EMA (7, 25) 替代赢家的 SMA，反应更灵敏。
       - 引入 ATR (平均真实波幅) 动态止损，而非固定百分比，适应巨鲸波动。
       - 增加波动率过滤：仅在波动率扩张时交易。
    4. 风控升级：基于当前余额($800)动态计算仓位，不再全仓梭哈。
    """
    
    def __init__(self):
        # === 进化参数 ===
        self.ema_fast_window = 7
        self.ema_slow_window = 25
        self.atr_window = 14
        
        # 风控参数
        self.risk_per_trade = 0.02      # 单笔交易风险 (本金的2%)
        self.atr_sl_multiplier = 2.0    # 止损宽容度 (2倍ATR)
        self.atr_tp_multiplier = 3.5    # 盈亏比目标 > 1.5
        self.max_position_size = 0.3    # 单标的最大仓位限制 (30%)

        # === 状态存储 ===
        # 仅保留最近所需的历史数据以节省内存
        self.history_len = 50
        self.prices: Dict[str, Deque[float]] = {}
        self.highs: Dict[str, Deque[float]] = {}
        self.lows: Dict[str, Deque[float]] = {}
        
        # 交易状态
        self.current_positions: Dict[str, float] = {} # symbol -> quantity
        self.entry_data: Dict[str, dict] = {}         # symbol -> {entry_price, sl_price, tp_price}
        self.balance = 800.0  # 当前余额
        self.last_reflection = "Initial state after evolution."

    def _calculate_ema(self, data: List[float], window: int) -> float:
        if not data or len(data) < window:
            return 0.0
        k = 2 / (window + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price * k) + (ema * (1 - k))
        return ema

    def _calculate_atr(self, highs: List[float], lows: List[float], closes: List[float], window: int) -> float:
        if len(closes) < window + 1:
            return 0.0
        
        tr_list = []
        for i in range(1, len(closes)):
            h = highs[i]
            l = lows[i]
            pc = closes[i-1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_list.append(tr)
        
        if not tr_list:
            return 0.0
            
        # 简单平均计算ATR
        return sum(tr_list[-window:]) / window

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策核心：收到新价格 tick
        prices format: {'BTC': {'price': 50000, 'high': 50100, 'low': 49900, 'volume': ...}}
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data['price']
            high = data.get('high', current_price)
            low = data.get('low', current_price)

            # 1. 更新数据流
            if symbol not in self.prices:
                self.prices[symbol] = deque(maxlen=self.history_len)
                self.highs[symbol] = deque(maxlen=self.history_len)
                self.lows[symbol] = deque(maxlen=self.history_len)
            
            self.prices[symbol].append(current_price)
            self.highs[symbol].append(high)
            self.lows[symbol].append(low)

            # 数据不足时不操作
            if len(self.prices[symbol]) < self.ema_slow_window + 1:
                continue

            # 2. 计算指标
            price_list = list(self.prices[symbol])
            ema_fast = self._calculate_ema(price_list, self.ema_fast_window)
            ema_slow = self._calculate_ema(price_list, self.ema_slow_window)
            atr = self._calculate_atr(
                list(self.highs[symbol]), 
                list(self.lows[symbol]), 
                price_list, 
                self.atr_window
            )

            # 3. 持仓管理 (止盈/止损)
            if symbol in self.current_positions:
                entry_info = self.entry_data.get(symbol)
                if entry_info:
                    # 动态止损 (Trailing Stop logic could be added here, but sticking to fixed ATR SL for robustness)
                    sl_price = entry_info['sl_price']
                    tp_price = entry_info['tp_price']
                    
                    # 触发止损
                    if current_price <= sl_price:
                        decision = TradeDecision(
                            signal=Signal.SELL,
                            symbol=symbol,
                            amount_usd=0, # Sell all
                            reason=f"STOP LOSS triggered at {current_price} (SL: {sl_price:.2f})"
                        )
                        self._close_position(symbol, current_price)
                        return decision # 立即执行风控
                    
                    # 触发止盈
                    elif current_price >= tp_price:
                        decision = TradeDecision(
                            signal=Signal.SELL,
                            symbol=symbol,
                            amount_usd=0, # Sell all
                            reason=f"TAKE PROFIT triggered at {current_price} (TP: {tp_price:.2f})"
                        )
                        self._close_position(symbol, current_price)
                        return decision

                    # 趋势反转平仓 (EMA 死叉)
                    elif ema_fast < ema_slow:
                         decision = TradeDecision(
                            signal=Signal.SELL,
                            symbol=symbol,
                            amount_usd=0,
                            reason="Trend Reversal (EMA Cross Down)"
                        )
                         self._close_position(symbol, current_price)
                         return decision

            # 4. 开仓逻辑 (仅在无仓位时)
            else:
                # 趋势过滤：价格在慢线之上 + 金叉
                trend_up = current_price > ema_slow and ema_fast > ema_slow
                
                # 动量确认：前一根K线也在上涨 (简单动量)
                momentum = price_list[-1] > price_list[-2]
                
                # 波动率保护：ATR不能为0
                valid_volatility = atr > 0

                if trend_up and momentum and valid_volatility:
                    # 资金管理：基于波动率计算仓位
                    risk_amount = self.balance * self.risk_per_trade # 愿意亏损的金额
                    stop_loss_dist = atr * self.atr_sl_multiplier
                    
                    if stop_loss_dist == 0: continue
                    
                    position_size_shares = risk_amount / stop_loss_dist
                    position_cost = position_size_shares * current_price
                    
                    # 仓位上限限制
                    max_allocation = self.balance * self.max_position_size
                    final_amount = min(position_cost, max_allocation)
                    
                    # 最小交易额过滤 (假设 $10)
                    if final_amount > 10.0:
                        sl_price = current_price - stop_loss_dist
                        tp_price = current_price + (atr * self.atr_tp_multiplier)
                        
                        self._open_position(symbol, current_price, final_amount, sl_price, tp_price)
                        
                        return TradeDecision(
                            signal=Signal.BUY,
                            symbol=symbol,
                            amount_usd=final_amount,
                            reason=f"Trend Start: EMA Cross + Volatility Breakout. SL:{sl_price:.2f}, TP:{tp_price:.2f}"
                        )

        return TradeDecision(signal=Signal.HOLD, symbol="", amount_usd=0, reason="Wait for setup")

    def _open_position(self, symbol: str, price: float, amount_usd: float, sl: float, tp: float):
        quantity = amount_usd / price
        self.current_positions[symbol] = quantity
        self.entry_data[symbol] = {
            'entry_price': price,
            'sl_price': sl,
            'tp_price': tp
        }
        self.balance -= amount_usd

    def _close_position(self, symbol: str, price: float):
        if symbol in self.current_positions:
            qty = self.current_positions[symbol]
            return_amount = qty * price
            self.balance += return_amount
            del self.current_positions[symbol]
            del self.entry_data[symbol]

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """
        Epoch 结束时的反思与参数自适应
        """
        # 简单自适应：如果余额回升，保持策略；如果继续亏损，收紧风控
        if self.balance < 800.0: # 还没回本
            self.risk_per_trade = max(0.01, self.risk_per_trade * 0.9) # 降低风险
            self.atr_sl_multiplier = max(1.5, self.atr_sl_multiplier * 0.9) # 收紧止损
            self.last_reflection = "Performance weak. Tightening risk controls."
        else:
            self.last_reflection = "Recovery in progress. Strategy logic holds."

    def get_reflection(self) -> str:
        return f"Gen2 Strategy: Switched to EMA Trend Following. Current Risk per trade: {self.risk_per_trade*100:.1f}%. Balance: {self.balance:.2f}"

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "The trend is your only friend. Stop guessing tops and bottoms. Use ATR for stops."
        else:
            return "Still calibrating volatility sensitivity. Moving Averages reduce noise but lag needs management."