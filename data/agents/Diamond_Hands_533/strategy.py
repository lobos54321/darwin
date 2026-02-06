# Darwin SDK - User Strategy Template
# Agent: Diamond_Hands_533 (Gen 4 - "Adaptive Predator")
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import math
import statistics
from collections import deque, defaultdict
from typing import Dict, List, Optional, Set

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized: Adaptive Predator v4.0")
        
        # === 核心配置 (Configuration) ===
        self.balance = 536.69           # 当前余额
        self.max_positions = 4          # 最大持仓数量
        self.trade_allocation = 0.22    # 单笔交易仓位 (22%)
        
        # === 策略参数 (Parameters) ===
        self.window_size = 15           # 价格窗口大小
        self.volatility_window = 10     # 波动率计算窗口
        self.buy_threshold_std = 1.2    # 买入阈值 (标准差倍数)
        self.trailing_stop_pct = 0.04   # 4% 移动止损 (比上一代宽松)
        self.hard_stop_loss = 0.08      # 8% 硬止损 (防止归零)
        self.min_volume_filter = 1000   # 最小成交量过滤 (模拟)
        
        # === 内部状态 (State) ===
        self.last_prices: Dict[str, float] = {}
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.window_size))
        self.positions: Dict[str, Dict] = {} # symbol -> {entry_price, highest_price, amount}
        self.banned_tags: Set[str] = set()
        self.boosted_tags: Set[str] = set()
        
        # === 进化特征 (Evolutionary Traits) ===
        # 1. 动量惯性 (Momentum Inertia): 记录连续上涨次数
        self.momentum_streak: Dict[str, int] = defaultdict(int)

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        # 处理惩罚信号 - 立即加入黑名单并清仓
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ HIVE PENALTY: {penalize}")
            self.banned_tags.update(penalize)
            for tag in penalize:
                if tag in self.positions:
                    self._execute_sell(tag, self.last_prices.get(tag, 0), "HIVE_BAN")

        # 处理加速信号 - 降低该资产的买入由于
        boost = signal.get("boost", [])
        if boost:
            print(f"🚀 HIVE BOOST: {boost}")
            self.boosted_tags.update(boost)

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        Args:
            prices (dict): {"SYMBOL": {"priceUsd": 10.5, "tags": ["MEME"], ...}}
        """
        decisions = []
        
        # 1. 更新数据与维护持仓
        for symbol, data in prices.items():
            current_price = data.get("priceUsd", 0)
            if current_price <= 0: continue
            
            tags = data.get("tags", [])
            
            # 记录历史价格
            self.price_history[symbol].append(current_price)
            self.last_prices[symbol] = current_price
            
            # 检查是否在黑名单
            if any(t in self.banned_tags for t in tags) or symbol in self.banned_tags:
                if symbol in self.positions:
                    self._execute_sell(symbol, current_price, "BANNED_TAG_EXIT")
                continue

            # --- 持仓管理 (Sell Logic) ---
            if symbol in self.positions:
                self._manage_position(symbol, current_price)
            
            # --- 开仓机会寻找 (Buy Logic) ---
            else:
                if len(self.positions) < self.max_positions:
                    if self._check_buy_signal(symbol, current_price, tags):
                        amount = self.balance * self.trade_allocation
                        self._execute_buy(symbol, current_price, amount)

        return decisions

    def _manage_position(self, symbol: str, current_price: float):
        """管理现有持仓：移动止损与硬止损"""
        pos = self.positions[symbol]
        
        # 更新最高价 (High Water Mark)
        if current_price > pos['highest_price']:
            pos['highest_price'] = current_price
            
        # 计算回撤
        drawdown = (pos['highest_price'] - current_price) / pos['highest_price']
        pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
        
        # 逻辑 1: 硬止损 (防灾难)
        if pnl_pct < -self.hard_stop_loss:
            self._execute_sell(symbol, current_price, f"HARD_STOP_LOSS {pnl_pct*100:.2f}%")
            return

        # 逻辑 2: 动态移动止损 (Trailing Stop)
        # 如果盈利超过 10%，收紧止损到 2%
        dynamic_trail = 0.02 if pnl_pct > 0.10 else self.trailing_stop_pct
        
        if drawdown > dynamic_trail:
            reason = "TAKE_PROFIT" if pnl_pct > 0 else "TRAILING_STOP"
            self._execute_sell(symbol, current_price, f"{reason} (DD: {drawdown*100:.2f}%)")

    def _check_buy_signal(self, symbol: str, current_price: float, tags: List[str]) -> bool:
        """基于统计学的突破策略"""
        history = self.price_history[symbol]
        
        # 数据不足时不交易
        if len(history) < self.window_size:
            return False
            
        # 计算基础统计量
        prices = list(history)
        mean_price = statistics.mean(prices[:-1]) # 不包含当前价格的均值
        stdev = statistics.stdev(prices[:-1]) if len(prices) > 2 else 0
        
        if stdev == 0: return False

        # Z-Score 计算 (当前价格偏离均值多少个标准差)
        z_score = (current_price - mean_price) / stdev
        
        # 进化特征：如果是 Boosted 标签，降低门槛
        threshold = self.buy_threshold_std
        if any(t in self.boosted_tags for t in tags):
            threshold *= 0.7  # 降低 30% 门槛
            
        # 信号：价格向上突破布林带上轨 (Mean + N*Std) 且 动量为正
        is_breakout = z_score > threshold
        
        # 简单的趋势过滤：当前价格必须高于 SMA(5)
        sma_short = statistics.mean(prices[-5:])
        is_uptrend = current_price > sma_short
        
        if is_breakout and is_uptrend:
            # 避免追高：如果 Z-Score 过大 (>3.5)，认为是极端行情，可能反转，不买
            if z_score > 3.5:
                return False
            return True
            
        return False

    def _execute_buy(self, symbol: str, price: float, amount_usd: float):
        """执行买入模拟"""
        if self.balance < amount_usd:
            amount_usd = self.balance
            
        if amount_usd < 10: return # 忽略过小额度

        print(f"🔵 BUY {symbol} @ ${price:.4f} | Amt: ${amount_usd:.2f}")
        self.positions[symbol] = {
            'entry_price': price,
            'highest_price': price,
            'amount': amount_usd / price,
            'cost_basis': amount_usd
        }
        self.balance -= amount_usd
        self.momentum_streak[symbol] = 0

    def _execute_sell(self, symbol: str, price: float, reason: str):
        """执行卖出模拟"""
        pos = self.positions.pop(symbol)
        revenue = pos['amount'] * price
        profit = revenue - pos['cost_basis']
        self.balance += revenue
        
        icon = "🟢" if profit > 0 else "🔴"
        print(f"{icon} SELL {symbol} @ ${price:.4f} | PnL: ${profit:.2f} | {reason}")
        print(f"💰 New Balance: ${self.balance:.2f}")