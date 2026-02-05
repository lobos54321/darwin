# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (Basic v1.0)")
        self.last_prices = {}
        self.history = {} # Store simple history for MA calculation

    def on_price_update(self, prices: dict):
        """
        Called every time price updates (approx every 3s).
        
        Args:
            prices (dict): {
                "MOLT": {"priceUsd": 0.05, "priceChange24h": 5.2 ...},
                "CLANKER": {"priceUsd": 12.50, ...}
            }
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            last_price = self.last_prices.get(symbol, current_price)
            
            # Calculate % change since last update
            pct_change = ((current_price - last_price) / last_price) * 100 if last_price > 0 else 0
            
            # --- 基础策略逻辑 (Basic Strategy Logic) ---
            
            # 1. 追涨策略 (Momentum): 价格上涨超过 0.5%
            if pct_change > 0.5:
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": 10.0,
                    "reason": ["MOMENTUM_UP", "CHASING_PUMP"] # 🏷️ 标签：追涨
                }
            
            # 2. 抄底策略 (Mean Reversion): 价格暴跌超过 1.0%
            elif pct_change < -1.0:
                 decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": 20.0, # 抄底买多点
                    "reason": ["DIP_BUY", "OVERSOLD"] # 🏷️ 标签：抄底
                }
            
            # 3. 随机漫步 (Random Walk): 增加一点市场噪音，作为对照组
            elif random.random() < 0.05:
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": 5.0,
                    "reason": ["RANDOM_TEST"] # 🏷️ 标签：随机测试
                }

            # Update history
            self.last_prices[symbol] = current_price
            
            if decision:
                return decision
                
        return None # Hold
