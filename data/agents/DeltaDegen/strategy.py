```python
# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (DeltaDegen v2.0 - Evolutionary Update)")
        
        # --- 进化参数配置 (Evolution Config) ---
        self.history_length = 20       # 价格窗口大小
        self.stop_loss_pct = 0.05      # 5% 硬止损 (防守)
        self.take_profit_pct = 0.20    # 20% 止盈 (进攻)
        self.trailing_stop_pct = 0.04  # 4% 移动止损 (保住利润)
        self.max_positions = 3         # 最大持仓数 (分散风险)
        self.min_volatility = 0.002    # 最小波动率要求 (避免死水)
        
        # --- 内部状态 (Internal State) ---
        self.price_history = {}        # {symbol: deque(maxlen=20)}
        self.positions = {}            # {symbol: {'entry': float, 'high': float}}
        self.banned_tags = set()       # Hive Mind