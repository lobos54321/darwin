import math
import statistics
from typing import Dict, List, Optional
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
    Agent_006 进化版: "Phoenix Protocol" (凤凰协议)
    
    【策略重构 - 绝地反击模式】
    针对当前仅剩 $16.49 的极端情况，常规策略已失效。
    本策略采用 "极高波动率捕捉 + 移动止盈" 的生存模式。
    
    进化特征:
    1. 资金管理 (Survival Mode): 当资金 < $50 时，采用 "全仓狙击" 模式 (All-in 单一最强标的)，
       利用复利尝试快速翻本。
    2. 入场逻辑 (Winner's DNA + Mutation): 结合布林带 (Bollinger Bands) 突破与 RSI 动量。
       只做 "口袋支点" (Pocket Pivot) —— 价格突破布林上轨且 RSI 未超买 (<75)。
    3. 出场逻辑 (Tight Control): 
       - 移动止盈: 价格每上涨 1%，止损线向上移动。
       - 硬止损: -2% 立即斩仓，绝不扛单。
    """

    def __init__(self):
        # === 核心参数 ===
        self.bb_window = 20           # 布林带周期
        self.bb_std_dev = 2.0         # 布林带标准差倍数
        self.rsi_window = 14          # RSI 周期
        
        # === 风险管理 ===
        self.max_positions = 1        # 资金少时只持有一只
        self.stop_loss_pct = 0.02     # 2% 硬止损
        self.trailing_gap = 0.03      # 3% 移动止盈回撤阈值
        
        # === 状态记录 ===
        self.price_history: Dict[str, List[float]] = {}
        self.current_positions: Dict[str, float] = {}  # symbol -> amount_usd
        self.entry_prices: Dict[str, float] = {}       # symbol -> entry price
        self.highest_prices: Dict[str, float] = {}     # symbol -> highest price since entry
        self.balance = 16.49  # Sync with current state
        self.last_reflection = "Initialized Phoenix Protocol."

    def _calculate_indicators(self, symbol: str) -> dict:
        prices = self.price_history[symbol]
        if len(prices) < self.bb_window:
            return {}
            
        # SMA & Bollinger Bands
        recent = prices[-self.bb_window:]
        sma = statistics.mean(recent)
        stdev = statistics.stdev(recent)
        upper_band = sma + (stdev * self.bb_std_dev)
        lower_band = sma - (stdev * self.bb_std_dev)
        
        # RSI
        if len(prices) < self.rsi_window + 1:
            rsi = 50
        else:
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            recent_deltas = deltas[-self.rsi_window:]
            up = [d for d in recent_deltas if d > 0]
            down = [abs(d) for d in recent_deltas if d < 0]
            avg_gain = sum(up) / self.rsi_window if up else 0
            avg_loss = sum(down) / self.rsi_window if down else 0.0001
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return {
            "sma": sma,
            "upper": upper_band,
            "lower": lower_band,
            "rsi": rsi,
            "price": prices[-1]
        }

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        # 1. 更新数据
        active_symbols = []
        for symbol, data in prices.items():
            # 兼容不同的数据格式 (float 或 dict)
            current_price = data['price'] if isinstance(data, dict) and 'price' in data else data
            if isinstance(current_price, (int, float)):
                if symbol not in self.price_history:
                    self.price_history[symbol] = []
                self.price_history[symbol].append(float(current_price))
                active_symbols.append(symbol)
                
                # 更新持仓最高价用于移动止盈
                if symbol in self.current_positions:
                    self.highest_prices[symbol] = max(self.highest_prices.get(symbol, 0), current_price)

        # 2. 检查持仓 (卖出逻辑)
        for symbol in list(self.current_positions.keys()):
            current_price = self.price_history[symbol][-1]
            entry_price = self.entry_prices[symbol]
            highest_price = self.highest_prices[symbol]
            position_value = self.current_positions[symbol]
            
            # 计算收益率
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown_from_high = (highest_price - current_price) / highest_price
            
            # A. 硬止损
            if pnl_pct < -self.stop_loss_pct:
                self.balance += position_value * (1 + pnl_pct) # 模拟回款
                del self.current_positions[symbol]
                return TradeDecision(Signal.SELL, symbol, position_value, "STOP_LOSS_HIT")
            
            # B. 移动止盈 (Trailing Stop)
            # 如果盈利超过 5%，则回撤 3% 出场；如果盈利微薄，则放宽
            dynamic_trail = self.trailing_gap if pnl_pct > 0.05 else 0.05
            if pnl_pct > 0.01 and drawdown_from_high > dynamic_trail:
                self.balance += position_value * (1 + pnl_pct)
                del self.current_positions[symbol]
                return TradeDecision(Signal.SELL, symbol, position_value, "TRAILING_PROFIT")

        # 3. 检查开仓 (买入逻辑)
        # 如果已经满仓 (对于 $16 本金，1个持仓即满仓)，则不操作
        if len(self.current_positions) >= self.max_positions:
            return None

        best_score = -1
        best_symbol = None
        
        for symbol in active_symbols:
            if symbol in self.current_positions:
                continue
                
            inds = self._calculate_indicators(symbol)
            if not inds:
                continue
                
            price = inds['price']
            upper = inds['upper']
            rsi = inds['rsi']
            sma = inds['sma']
            
            # 凤凰策略核心: 
            # 1. 价格必须在 SMA 之上 (右侧交易)
            # 2. 价格突破上轨 (动量爆发)
            # 3. RSI 处于 55-75 之间 (强势但未极度超买)
            if price > sma and price > upper and 55 < rsi < 75:
                # 评分: RSI 越高越好，但不能超过 80
                score = rsi
                if score > best_score:
                    best_score = score
                    best_symbol = symbol

        # 4. 执行买入
        if best_symbol:
            # 资金极少时，梭哈 98% 余额 (留 2% 容错/手续费)
            invest_amount = self.balance * 0.98
            if invest_amount < 1.0: # 余额太低无法交易
                return None
                
            self.balance -= invest_amount
            self.current_positions[best_symbol] = invest_amount
            self.entry_prices[best_symbol] = self.price_history[best_symbol][-1]
            self.highest_prices[best_symbol] = self.price_history[best_symbol][-1]
            
            return TradeDecision(
                Signal.BUY, 
                best_symbol, 
                invest_amount, 
                f"PHOENIX_BREAKOUT: RSI={best_score:.1f}"
            )

        return None

    def on_epoch_end(self, rankings: List[dict], winner_wisdom: str):
        """每轮结束更新策略参数"""
        # 如果本轮又是亏损，收紧止损
        if self.balance < 16.0: 
            self.stop_loss_pct = 0.015 # 进一步收紧
        
        # 记录反思
        self.last_reflection = f"Balance: ${self.balance:.2f}. Strategy: Full-Force Breakout. Status: {'Surviving' if self.balance > 10 else 'Critical'}."

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Concentration is the key to recovery. Diversification preserves wealth; concentration builds it."
        return "Adapting to extreme volatility conditions. Seeking asymmetric risk-reward setups."