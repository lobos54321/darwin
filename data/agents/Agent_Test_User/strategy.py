# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Evolved: AdaptiveVolatilityPredator_v3")
        
        # --- 基因变异参数 (Evolution Parameters) ---
        self.window_size = 30           # 增加样本窗口以过滤噪音
        self.std_dev_multiplier = 2.0   # 布林带突破阈值
        self.momentum_threshold = 0.5   # 最小动量要求 (%)
        
        # --- 风控参数 (Risk Management) ---
        self.stop_loss_pct = 0.04       # 4% 硬止损 (收紧)
        self.trailing_stop_pct = 0.02   # 2% 移动止盈 (保护利润)
        self.max_position_size = 0.25   # 单笔交易最大仓位 (25% 余额)
        
        # --- 记忆系统 (Memory System) ---
        self.price_history = {}         # {symbol: deque(maxlen=window_size)}
        self.positions = {}             # {symbol: {'entry_price': float, 'highest_price': float, 'amount': float}}
        self.token_performance = {}     # {symbol: net_pnl} - 优胜劣汰机制
        self.banned_tags = set()
        self.cooldowns = {}             # {symbol: int}

    def on_hive_signal(self, signal: dict):
        """处理 Hive Mind 信号"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🛡️ Adaptive Defense: Penalizing {penalize}")
            self.banned_tags.update(penalize)
            # 立即清算被惩罚的资产
            for tag in penalize:
                if tag in self.positions:
                    self._force_close(tag)

    def on_price_update(self, prices: dict):
        """
        核心交易逻辑 - 每 ~3秒调用一次
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # 1. 更新数据流
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(current_price)
            
            # 冷却期管理
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]
                continue

            # 2. 持仓管理 (止损/止盈)
            if symbol in self.positions:
                decision = self._manage_position(symbol, current_price)
                if decision:
                    return decision # 每次更新只执行一个动作以保证稳定性
                continue # 如果持有仓位且未卖出，不进行买入判断

            # 3. 机会扫描 (仅针对未持仓且未被禁用的代币)
            if symbol not in self.banned_tags and len(self.price_history[symbol]) >= self.window_size:
                # 检查代币历史表现 (Darwinian Selection)
                if self.token_performance.get(symbol, 0) < -0.1: # 如果该代币历史亏损超过 10%
                    continue 

                decision = self._evaluate_entry(symbol, current_price)
                if decision:
                    return decision

        return None

    def _manage_position(self, symbol, current_price):
        """仓位管理：移动止盈与硬止损"""
        pos = self.positions[symbol]
        entry_price = pos['entry_price']
        
        # 更新最高价格记录 (用于移动止盈)
        if current_price > pos['highest_price']:
            pos['highest_price'] = current_price
            
        # 计算当前盈亏比
        pnl_pct = (current_price - entry_price) / entry_price
        # 计算从最高点回撤幅度
        drawdown_pct = (pos['highest_price'] - current_price) / pos['highest_price']
        
        action = None
        reason = ""

        # A. 硬止损触发
        if pnl_pct <= -self.stop_loss_pct:
            action = "SELL"
            reason = "Stop Loss"
            
        # B. 移动止盈触发 (只有在盈利状态下才激活)
        elif current_price > entry_price and drawdown_pct >= self.trailing_stop_pct:
            action = "SELL"
            reason = "Trailing Profit"
            
        if action == "SELL":
            print(f"📉 {action} {symbol}: {reason} (PnL: {pnl_pct*100:.2f}%)")
            # 记录代币表现
            self.token_performance[symbol] = self.token_performance.get(symbol, 0) + pnl_pct
            # 移除持仓
            del self.positions[symbol]
            # 设置冷却，避免立即买回
            self.cooldowns[symbol] = 10 
            return (action, symbol, 1.0) # 1.0 表示卖出全部

        return None

    def _evaluate_entry(self, symbol, current_price):
        """入场逻辑：基于波动率突破 (Bollinger Breakout Variant)"""
        history = self.price_history[symbol]
        
        # 计算统计数据
        mean_price = statistics.mean(history)
        stdev = statistics.stdev(history) if len(history) > 1 else 0
        
        if stdev == 0: return None

        # 逻辑：价格突破上轨 (Mean + 2*StdDev) 且动量向上
        upper_band = mean_price + (stdev * self.std_dev_multiplier)
        
        # 动量计算 (当前价格 vs 5个周期前)
        lookback_idx = max(0, len(history) - 5)
        momentum_price = history[lookback_idx]
        momentum_pct = ((current_price - momentum_price) / momentum_price) * 100
        
        # 信号触发条件
        if current_price > upper_band and momentum_pct > self.momentum_threshold:
            print(f"🚀 BUY Signal {symbol}: Breakout (Price {current_price:.4f} > Band {upper_band:.4f})")
            
            # 记录持仓
            self.positions[symbol] = {
                'entry_price': current_price,
                'highest_price': current_price,
                'amount': 0 # 具体数量由 SDK 执行层处理，这里仅标记状态
            }
            return ("BUY", symbol, self.max_position_size)
            
        return None

    def _force_close(self, symbol):
        """强制平仓辅助函数"""
        if symbol in self.positions:
            del self.positions[symbol]