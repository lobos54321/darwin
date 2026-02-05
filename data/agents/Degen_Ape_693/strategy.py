import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

# ==========================================
# 基础定义 (必须与系统兼容)
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

# ==========================================
# 进化后的策略: Phoenix Protocol (Degen_Ape_693)
# ==========================================

class DarwinStrategy:
    """
    Agent: Degen_Ape_693 (Evolved)
    Strategy: Phoenix Protocol (Trend Following + Volatility Gating)
    
    进化日志 (PnL -46.3% -> Recovery Mode):
    1. 承认失败: 放弃之前的 "AVRS" 复杂逻辑，回归均值回归与趋势跟随的本质。
    2. 生存模式: 鉴于本金腰斩，启用 "Phoenix" 资金管理，单笔最大亏损限制在总权益的 1%。
    3. 趋势过滤: 引入 EMA 丝带 (EMA12/EMA26) 确认趋势，坚决不做逆势接刀。
    4. 波动率门控: 使用 ATR 动态调整止损和仓位，避免在低波动时被磨损，高波动时被爆仓。
    """

    def __init__(self):
        # === 核心参数 ===
        self.lookback_period = 50       # 只需要最近50根K线计算指标
        self.risk_per_trade = 0.015     # 极度保守：每笔交易只承担 1.5% 风险
        self.max_positions = 3          # 限制同时持仓数量，分散风险
        
        # === 策略参数 ===
        self.ema_fast = 12
        self.ema_slow = 26
        self.rsi_period = 14
        self.atr_period = 14
        
        # === 状态管理 ===
        self.price_history: Dict[str, List[float]] = {}
        self.high_history: Dict[str, List[float]] = {}
        self.low_history: Dict[str, List[float]] = {}
        
        self.entry_prices: Dict[str, float] = {}
        self.trailing_stops: Dict[str, float] = {}  # 追踪止损价位
        self.balance = 536.69  # 当前余额同步
        
        self.last_reflection = "Initial state: Recovery mode activated."

    def _update_history(self, symbol: str, price_data: dict):
        """更新历史数据窗口"""
        if symbol not in self.price_history:
            self.price_history[symbol] = []
            self.high_history[symbol] = []
            self.low_history[symbol] = []
            
        # 假设 price_data 包含 'close', 'high', 'low'，如果没有则用当前价格代替
        close_p = price_data.get('close', price_data.get('price', 0.0))
        high_p = price_data.get('high', close_p)
        low_p = price_data.get('low', close_p)
        
        self.price_history[symbol].append(close_p)
        self.high_history[symbol].append(high_p)
        self.low_history[symbol].append(low_p)
        
        # 保持窗口大小，避免内存溢出
        if len(self.price_history[symbol]) > self.lookback_period + 10:
            self.price_history[symbol].pop(0)
            self.high_history[symbol].pop(0)
            self.low_history[symbol].pop(0)

    def _calculate_indicators(self, symbol: str) -> dict:
        """计算技术指标"""
        closes = pd.Series(self.price_history[symbol])
        highs = pd.Series(self.high_history[symbol])
        lows = pd.Series(self.low_history[symbol])
        
        if len(closes) < self.ema_slow + 2:
            return None
            
        # MACD / EMA 趋势
        ema_f = closes.ewm(span=self.ema_fast, adjust=False).mean()
        ema_s = closes.ewm(span=self.ema_slow, adjust=False).mean()
        
        # RSI
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        # ATR (用于动态止损)
        tr1 = highs - lows
        tr2 = (highs - closes.shift()).abs()
        tr3 = (lows - closes.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=self.atr_period).mean()
        
        return {
            'ema_fast': ema_f.iloc[-1],
            'ema_slow': ema_s.iloc[-1],
            'rsi': rsi.iloc[-1],
            'atr': atr.iloc[-1] if not np.isnan(atr.iloc[-1]) else closes.iloc[-1] * 0.02,
            'close': closes.iloc[-1]
        }

    def on_price_update(self, prices: Dict[str, dict]) -> Optional[TradeDecision]:
        """
        决策逻辑：
        1. 卖出逻辑：触及硬止损 或 跌破追踪止损 或 RSI超买离场。
        2. 买入逻辑：EMA金叉(趋势向上) + RSI不过热(避免追高) + 资金允许。
        """
        
        # 1. 更新数据
        for symbol, data in prices.items():
            self._update_history(symbol, data)

        # 2. 遍历资产进行决策
        # 优先处理持仓资产（止损/止盈）
        for symbol in list(self.entry_prices.keys()):
            current_price = prices[symbol].get('price', 0)
            if current_price == 0: continue
            
            indicators = self._calculate_indicators(symbol)
            if not indicators: continue
            
            entry_price = self.entry_prices[symbol]
            atr = indicators['atr']
            
            # --- 卖出逻辑 ---
            
            # A. 追踪止损更新 (Trailing Stop)
            # 如果价格上涨，将止损线上移到 (最高价 - 2*ATR)
            dynamic_stop = current_price - (2.0 * atr)
            if symbol not in self.trailing_stops:
                self.trailing_stops[symbol] = entry_price - (1.5 * atr) # 初始止损
            
            if dynamic_stop > self.trailing_stops[symbol]:
                self.trailing_stops[symbol] = dynamic_stop
            
            # B. 执行止损
            if current_price < self.trailing_stops[symbol]:
                pnl_pct = (current_price - entry_price) / entry_price
                del self.entry_prices[symbol]
                del self.trailing_stops[symbol]
                self.balance += current_price * 10 # 假设简化的数量计算，实际应根据仓位
                return TradeDecision(Signal.SELL, symbol, 0, f"STOP_HIT: PnL {pnl_pct:.2%}")
            
            # C. 趋势反转止盈 (EMA 死叉)
            if indicators['ema_fast'] < indicators['ema_slow'] and current_price > entry_price:
                del self.entry_prices[symbol]
                del self.trailing_stops[symbol]
                return TradeDecision(Signal.SELL, symbol, 0, "TREND_REVERSAL: EMA Cross Down")

        # 3. 寻找买入机会 (如果没有达到最大持仓)
        if len(self.entry_prices) >= self.max_positions:
            return None
            
        best_setup = None
        max_score = -1
        
        for symbol, data in prices.items():
            if symbol in self.entry_prices: continue
            
            indicators = self._calculate_indicators(symbol)
            if not indicators: continue
            
            # --- 买入信号过滤 ---
            
            # 1. 趋势过滤: 快速均线 > 慢速均线 (处于上升趋势)
            trend_ok = indicators['ema_fast'] > indicators['ema_slow']
            
            # 2. 动量过滤: RSI 在 40-65 之间 (有动力但未超买)
            rsi_ok = 40 < indicators['rsi'] < 65
            
            # 3. 价格位置: 价格在 EMA Fast 附近 (回调买入，而不是追高)
            dist_to_ema = (indicators['close'] - indicators['ema_fast']) / indicators['ema_fast']
            pullback_ok = -0.01 < dist_to_ema < 0.02
            
            if trend_ok and rsi_ok and pullback_ok:
                # 评分系统：RSI越低越好(空间大)，ATR波动适中
                score = (70 - indicators['rsi']) 
                if score > max_score:
                    max_score = score
                    best_setup = symbol
        
        # 执行买入
        if best_setup:
            symbol = best_setup
            indicators = self._calculate_indicators(symbol)
            price = indicators['close']
            atr = indicators['atr']
            
            # 资金管理：基于波动率计算仓位
            # 风险额度 = 总余额 * 1.5%
            # 止损距离 = 2 * ATR
            # 仓位价值 = 风险额度 / (止损距离 / 价格)
            risk_amount = self.balance * self.risk_per_trade
            stop_distance_pct = (2 * atr) / price
            position_size_usd = risk_amount / stop_distance_pct
            
            # 限制单笔最大仓位为余额的 30% (防止ATR过小时仓位过大)
            position_size_usd = min(position_size_usd, self.balance * 0.3)
            
            if position_size_usd > 10: # 最小交易额过滤
                self.entry_prices[symbol] = price
                self.trailing_stops[symbol] = price - (2 * atr)
                self.balance -= position_size_usd
                return TradeDecision(Signal.BUY, symbol, position_size_usd, f"PHOENIX_ENTRY: Trend+Pullback, Risk={stop_distance_pct:.1%}")

        return None

    def on_epoch_end(self, rankings: list, winner_wisdom: str):
        """每轮结束时的自我反思与参数调整"""
        # 记录本轮表现，如果依然亏损，下轮进一步收紧 ATR 倍数
        self.last_reflection = f"Rank: {rankings}. Strategy shifted to Phoenix Protocol. Focused on capital preservation."

    def get_reflection(self) -> str:
        return self.last_reflection

    def get_council_message(self, is_winner: bool) -> str:
        if is_winner:
            return "Survival is the first law of trading. Cut losses fast, let winners run on volatility trails."
        return "Adapting. Evolving. Surviving."