# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Evolved: BetaBot -> DeltaVanguard (Z-Score Momentum & Survival Mode)")
        
        # --- 账户与风控状态 (Account & Risk State) ---
        self.initial_balance = 1000.0
        self.current_balance = 639.51  # Updated from state
        
        # 进化变异：生存模式 (Survival Mode Mutation)
        # 由于回撤严重 (-36%)，我们将仓位缩小，通过高胜率小额交易恢复资金
        self.base_trade_pct = 0.05     # 每次仅投入当前余额的 5%
        self.max_positions = 5         # 分散持仓
        self.min_history_len = 15      # 需要至少 15 个数据点才计算指标
        
        # --- 策略参数 (Strategy Parameters) ---
        self.z_score_buy_threshold = 2.0   # 突破 2 倍标准差买入
        self.z_score_sell_threshold = 4.5  # 超过 4.5 倍标准差视为抛物线，止盈
        self.momentum_window = 3           # 短期动量窗口
        
        # --- 动态止损/止盈 (Dynamic Exit) ---
        self.hard_stop_loss = 0.05     # 5% 硬止损 (收紧)
        self.trailing_stop_activation = 0.08 # 盈利 8% 后激活追踪止损
        self.trailing_callback = 0.03  # 回撤 3% 出场
        
        # --- 记忆库 (Memory) ---
        # {symbol: deque(maxlen=30)} - 保存最近30次价格
        self.price_history = {}       
        # {symbol: {'entry_price': float, 'highest_price': float, 'amount': float, 'ticks_held': int}}
        self.positions = {}           
        self.banned_tags = set()
        self.cooldowns = {}           # {symbol: int}

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)

    def _calculate_stats(self, symbol):
        """计算价格序列的均值和标准差"""
        history = self.price_history.get(symbol)
        if not history or len(history) < self.min_history_len:
            return None, None
        
        prices = list(history)
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices) if len(prices) > 1 else 0
        return mean, stdev

    def on_price_update(self, prices: dict):
        """
        核心交易逻辑
        """
        decision = None
        
        # 1. 更新数据与维护冷却期
        for symbol, data in prices.items():
            price = data["priceUsd"]
            
            # 初始化历史记录
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=30)
            self.price_history[symbol].append(price)
            
            # 冷却期递减
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # 2. 管理现有持仓 (Exit Logic)
        # 优先处理卖出逻辑，防止亏损扩大
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]["priceUsd"]
            pos = self.positions[symbol]
            pos['ticks_held'] += 1
            
            # 更新最高价
            if current_price > pos['highest_price']:
                pos['highest_price'] = current_price
            
            # 计算收益率
            pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
            drawdown_from_high = (pos['highest_price'] - current_price) / pos['highest_price']
            
            should_sell = False
            reason = ""

            # A. 硬止损 (Hard Stop)
            if pnl_pct < -self.hard_stop_loss:
                should_sell = True
                reason = "Hard Stop Loss"
            
            # B. 追踪止损 (Trailing Stop)
            elif pnl_pct > self.trailing_stop_activation and drawdown_from_high > self.trailing_callback:
                should_sell = True
                reason = "Trailing Stop Hit"
            
            # C. 僵尸仓位清理 (Time Decay)
            # 如果持有超过 20 个 tick 且收益微薄 (<1%)，清仓释放资金
            elif pos['ticks_held'] > 20 and pnl_pct < 0.01:
                should_sell = True
                reason = "Stagnant Position"

            # D. 抛物线止盈 (Parabolic Take Profit)
            # 如果当前价格 Z-Score 极高，预示反转风险
            mean, stdev = self._calculate_stats(symbol)
            if mean and stdev > 0:
                z_score = (current_price - mean) / stdev
                if z_score > self.z_score_sell_threshold:
                    should_sell = True
                    reason = f"Parabolic Z-Score: {z_score:.2f}"

            if should_sell:
                amount = pos['amount']
                # 模拟卖出后余额增加 (实际由引擎处理，这里用于内部估算)
                self.current_balance += amount * current_price
                del self.positions[symbol]
                self.cooldowns[symbol] = 5 # 卖出后冷却5个tick
                print(f"📉 SELL {symbol} | PnL: {pnl_pct*100:.2f}% | Reason: {reason}")
                return {"action": "sell", "symbol": symbol, "amount": amount}

        # 3. 寻找开仓机会 (Entry Logic)
        # 如果持仓已满或余额不足，不操作
        if len(self.positions) >= self.max_positions or self.current_balance < 10:
            return None

        best_candidate = None
        highest_score = -1

        for symbol, data in prices.items():
            # 过滤条件
            if symbol in self.positions: continue
            if symbol in self.cooldowns: continue
            if symbol in self.banned_tags: continue
            
            mean, stdev = self._calculate_stats(symbol)
            if not mean or stdev == 0: continue
            
            current_price = data["priceUsd"]
            z_score = (current_price - mean) / stdev
            
            # 策略核心：Z-Score 突破 + 动量确认
            # 我们寻找 Z-Score > 2.0 (统计学显著上涨) 但 < 4.0 (未经过热)
            if self.z_score_buy_threshold < z_score < 4.0:
                # 动量检查：确保最近3个点是上涨趋势
                history = list(self.price_history[symbol])
                if len(history) >= 3 and history[-1] > history[-2] > history[-3]:
                    # 评分：Z-Score 越高越好（在限制范围内）
                    score = z_score
                    if score > highest_score:
                        highest_score = score
                        best_candidate = symbol

        # 执行买入
        if best_candidate:
            price = prices[best_candidate]["priceUsd"]
            # 动态仓位：基于当前余额的 5%
            trade_value = self.current_balance * self.base_trade_pct
            amount = trade_value / price
            
            self.positions[best_candidate] = {
                'entry_price': price,
                'highest_price': price,
                'amount': amount,
                'ticks_held': 0
            }
            self.current_balance -= trade_value
            print(f"🚀 BUY {best_candidate} | Price: {price} | Z-Score: {highest_score:.2f}")
            return {"action": "buy", "symbol": best_candidate, "amount": amount}

        return None