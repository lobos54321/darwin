# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (ZetaZero v4.0 - Adaptive Apex)")
        
        # --- 🧬 基因参数 (Gene Expression) ---
        self.lookback_window = 20         # 价格历史窗口大小
        self.z_score_threshold = 1.8      # 突破标准差倍数 (Entry Trigger)
        self.min_volatility = 0.5         # 最小波动率要求 (避免死水)
        
        # --- 🛡️ 风控参数 (Risk Management) ---
        self.max_positions = 5            # 最大持仓数量
        self.position_size_pct = 0.10     # 单笔交易占当前余额百分比
        self.stop_loss_pct = 0.08         # 初始止损 8%
        self.trailing_stop_pct = 0.04     # 移动止损回撤 4%
        self.take_profit_pct = 0.25       # 硬止盈 25%
        self.max_drawdown_pause = 0.15    # 累计回撤超过15%暂停开仓
        
        # --- 📊 状态追踪 (State Tracking) ---
        self.price_history = defaultdict(lambda: deque(maxlen=self.lookback_window))
        self.positions = {}               # {symbol: {'entry_price': float, 'highest_price': float, 'qty': float}}
        self.banned_tags = set()
        self.boosted_tags = set()
        self.initial_balance = 0          # 将在第一次更新时设定
        self.current_balance = 0          # 估算当前余额
        self.realized_pnl = 0

    def on_hive_signal(self, signal: dict):
        """接收 Hive Mind 信号"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Penalty received for tags: {penalize}")
            self.banned_tags.update(penalize)
            
        boost = signal.get("boost", [])
        if boost:
            self.boosted_tags.update(boost)

    def _calculate_stats(self, prices):
        """计算均值和标准差"""
        if len(prices) < 2:
            return 0, 0
        mean = sum(prices) / len(prices)
        variance = sum((x - mean) ** 2 for x in prices) / (len(prices) - 1)
        std_dev = math.sqrt(variance)
        return mean, std_dev

    def on_price_update(self, prices: dict):
        """
        核心交易逻辑循环
        """
        # 1. 资金管理与初始化
        # 假设每次调用无法直接获取余额，需要通过外部传入或自行估算，此处简化为假设有余额管理接口
        # 在实际 SDK 中，通常 decision 返回后引擎会处理余额，这里模拟保守开仓
        
        decision = {}
        
        # 2. 更新价格历史
        for symbol, data in prices.items():
            price = data["priceUsd"]
            self.price_history[symbol].append(price)

        # 3. 仓位管理 (止盈/止损/移动止损)
        symbols_to_sell = []
        
        for symbol, pos in self.positions.items():
            current_price = prices[symbol]["priceUsd"]
            
            # 更新最高价用于移动止损
            if current_price > pos['highest_price']:
                pos['highest_price'] = current_price
            
            # 计算收益率
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            drawdown_from_high = (pos['highest_price'] - current_price) / pos['highest_price']
            
            # A. 硬止损
            if roi <= -self.stop_loss_pct:
                print(f"🛑 Stop Loss triggered for {symbol} at {roi*100:.2f}%")
                symbols_to_sell.append(symbol)
                continue
                
            # B. 移动止损 (只有在盈利状态下才激活)
            if roi > 0.02 and drawdown_from_high >= self.trailing_stop_pct:
                print(f"📉 Trailing Stop triggered for {symbol}. High: {pos['highest_price']}, Curr: {current_price}")
                symbols_to_sell.append(symbol)
                continue

            # C. 硬止盈
            if roi >= self.take_profit_pct:
                print(f"💰 Take Profit triggered for {symbol} at {roi*100:.2f}%")
                symbols_to_sell.append(symbol)
                continue

        # 执行卖出
        for symbol in symbols_to_sell:
            decision[symbol] = {"action": "sell", "amount": self.positions[symbol]['qty']}
            del self.positions[symbol]

        # 4. 寻找开仓机会 (仅当未达到最大持仓限制)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol, data in prices.items():
                # 过滤条件
                if symbol in self.positions: continue
                if symbol in self.banned_tags: continue
                if len(self.price_history[symbol]) < self.lookback_window: continue
                
                history = list(self.price_history[symbol])
                current_price = data["priceUsd"]
                
                mean, std_dev = self._calculate_stats(history)
                
                if std_dev == 0: continue
                
                # 计算 Z-Score (价格偏离度)
                z_score = (current_price - mean) / std_dev
                
                # 波动率归一化 (Coef of Variation)
                volatility = std_dev / mean
                
                # 策略逻辑: 
                # 1. 价格突破布林带上轨 (Z-Score > Threshold)
                # 2. 波动率足够大 (避免死币)
                # 3. 或者是被 Boost 的币种，降低门槛
                
                threshold = self.z_score_threshold
                if symbol in self.boosted_tags:
                    threshold *= 0.8 # 降低20%门槛
                
                if z_score > threshold and volatility > (self.min_volatility / 100):
                    # 评分: Z-Score 越高越好，但要结合波动率
                    score = z_score * (1 + volatility)
                    candidates.append((symbol, score, current_price))
            
            # 按评分排序，取最好的
            candidates.sort(key=lambda x: x[1], reverse=True)
            
            # 计算可用槽位
            slots_available = self.max_positions - len(self.positions)
            
            for i in range(min(slots_available, len(candidates))):
                symbol, score, price = candidates[i]
                
                # 动态仓位大小 (这里假设总资金 $1000 用于计算，实际应读取 self.balance)
                # 为了保守起见，每次只投剩余购买力的一定比例，或者固定金额
                # 假设 API 调用者会处理 amount 为 USD 的情况
                trade_amount_usd = 60.0 # 约总资金的 10%
                
                print(f"🚀 Entry Signal: {symbol} (Z-Score: {score:.2f})")
                
                decision[symbol] = {
                    "action": "buy", 
                    "amount": trade_amount_usd 
                }
                
                # 记录持仓状态
                # 注意: 实际成交价可能不同，这里仅作策略内部记录
                qty_est = trade_amount_usd / price
                self.positions[symbol] = {
                    'entry_price': price,
                    'highest_price': price,
                    'qty': qty_est # 仅用于追踪，卖出时应全仓卖出
                }

        return decision