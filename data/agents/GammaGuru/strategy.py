# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import math
import random

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (GammaGuru v4.0 - Adaptive Recovery)")
        
        # 🛡️ 核心配置 (Core Configuration)
        self.balance = 639.51          # 同步当前余额用于计算仓位
        self.allocation_per_trade = 0.10 # 降低单笔风险至 10% (保守回血模式)
        self.max_positions = 5         # 分散投资
        self.min_volatility = 0.002    # 最小波动率阈值，过滤噪音
        
        # 🛑 风控参数 (Risk Management)
        self.stop_loss_pct = 0.04      # 4% 止损 (收紧止损)
        self.take_profit_pct = 0.08    # 8% 止盈 (积小胜为大胜)
        self.trailing_trigger = 0.05   # 盈利 5% 后激活移动止损
        self.trailing_gap = 0.02       # 移动止损回撤 2% 触发
        
        # 📊 状态追踪 (State Tracking)
        self.last_prices = {}
        self.holdings = {}             # {symbol: {'entry': float, 'high': float, 'qty': float}}
        self.banned_tags = set()
        self.trade_cooldown = {}       # 防止频繁交易
        self.tick_count = 0

    def on_hive_signal(self, signal: dict):
        """接收 Hive Mind 信号，优先处理风控"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Hive Penalty Received: {penalize}")
            self.banned_tags.update(penalize)
            
        # 收到惩罚信号时，如果持有相关资产，标记为需要立即卖出
        # (实际逻辑在 on_price_update 中执行以确保同步)

    def on_price_update(self, prices: dict):
        """
        主交易逻辑循环
        Args:
            prices (dict): {'SYMBOL': {'priceUsd': 1.23, 'priceChange24h': 5.0, ...}, ...}
        Returns:
            tuple: ('buy', symbol, amount_usd) or ('sell', symbol, fraction) or None
        """
        self.tick_count += 1
        decision = None
        
        # 1. 更新持仓最高价 & 检查被禁资产
        for symbol in list(self.holdings.keys()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            
            # 更新最高价用于移动止损
            if curr_price > self.holdings[symbol]['high']:
                self.holdings[symbol]['high'] = curr_price
                
            # 紧急清仓：如果资产被 Hive 封禁
            if symbol in self.banned_tags:
                print(f"🚫 Emergency Sell {symbol}: Banned Tag")
                del self.holdings[symbol]
                return ("sell", symbol, 1.0)

        # 2. 遍历市场寻找机会
        best_buy_score = -1
        best_buy_symbol = None
        
        for symbol, data in prices.items():
            current_price = data['priceUsd']
            last_price = self.last_prices.get(symbol, current_price)
            pct_change_tick = (current_price - last_price) / last_price if last_price > 0 else 0
            
            # 更新历史价格
            self.last_prices[symbol] = current_price
            
            # --- 卖出逻辑 (Sell Logic) ---
            if symbol in self.holdings:
                entry_price = self.holdings[symbol]['entry']
                high_price = self.holdings[symbol]['high']
                
                # 计算收益率
                pnl = (current_price - entry_price) / entry_price
                drawdown = (high_price - current_price) / high_price
                
                # A. 止损 (Stop Loss)
                if pnl <= -self.stop_loss_pct:
                    print(f"🛑 Stop Loss {symbol}: {pnl*100:.2f}%")
                    del self.holdings[symbol]
                    return ("sell", symbol, 1.0)
                
                # B. 移动止损 (Trailing Stop)
                if pnl >= self.trailing_trigger and drawdown >= self.trailing_gap:
                    print(f"💰 Trailing Stop {symbol}: Locked Profit {pnl*100:.2f}%")
                    del self.holdings[symbol]
                    return ("sell", symbol, 1.0)
                    
                # C. 止盈 (Take Profit)
                if pnl >= self.take_profit_pct:
                    print(f"🥂 Take Profit {symbol}: {pnl*100:.2f}%")
                    del self.holdings[symbol]
                    return ("sell", symbol, 1.0)
                
                continue # 已持仓，不重复买入

            # --- 买入逻辑 (Buy Logic) ---
            # 过滤条件：
            # 1. 不在黑名单
            # 2. 24小时趋势为正 (顺势)
            # 3. 当前 tick 涨幅 > 0 (动量)
            # 4. 冷却期已过
            if symbol in self.banned_tags: continue
            if len(self.holdings) >= self.max_positions: continue
            if self.trade_cooldown.get(symbol, 0) > self.tick_count: continue
            
            trend_24h = data.get('priceChange24h', 0)
            
            if trend_24h > 0 and pct_change_tick > self.min_volatility:
                # 评分系统：结合短期爆发力和长期趋势
                score = (pct_change_tick * 0.7) + (trend_24h * 0.01 * 0.3)
                if score > best_buy_score:
                    best_buy_score = score
                    best_buy_symbol = symbol

        # 执行买入
        if best_buy_symbol:
            trade_amount = self.balance * self.allocation_per_trade
            # 记录持仓
            self.holdings[best_buy_symbol] = {
                'entry': prices[best_buy_symbol]['priceUsd'],
                'high': prices[best_buy_symbol]['priceUsd'],
                'qty': trade_amount / prices[best_buy_symbol]['priceUsd'] # 估算
            }
            # 设置冷却，避免立即重复操作同一币种
            self.trade_cooldown[best_buy_symbol] = self.tick_count + 20 
            
            print(f"🚀 Buy Signal {best_buy_symbol}: Score {best_buy_score:.4f}")
            return ("buy", best_buy_symbol, trade_amount)

        return None