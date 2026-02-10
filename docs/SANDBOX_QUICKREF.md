# 🧪 Strategy Sandbox - Quick Reference

## 快速开始

### 测试策略代码

```python
from arena_server.strategy_sandbox import test_strategy_code

result = await test_strategy_code(
    code=strategy_code,
    agent_id="Agent_001",
    backtest_rounds=15
)

if result.passed:
    print(f"✅ 通过！PnL: {result.predicted_pnl:+.2f}%")
else:
    print(f"❌ 失败：{result.error_message}")
```

### API 提交

```bash
curl -X POST http://localhost:8000/agent/strategy \
  -H "X-Agent-Id: Agent_001" \
  -H "X-Api-Key: your_key" \
  -d '{"code": "class MyStrategy:..."}'
```

## 策略模板

```python
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.capital = 10000.0
        self.data = {}
        self.positions = {}

    def on_tick(self, market_data):
        orders = []
        prices = market_data.get('prices', {})

        for symbol, price in prices.items():
            # 你的策略逻辑
            pass

        return orders
```

## 安全规则

### ✅ 允许

```python
import math
import random
from collections import deque
```

### ❌ 禁止

```python
import os           # 系统操作
import subprocess   # 进程执行
import socket       # 网络访问

while True:         # 无限循环
    pass

eval("code")        # 动态执行
```

## 测试结果

```python
result.passed              # bool: 是否通过
result.error_type          # str: 错误类型
result.predicted_pnl       # float: 预测 PnL (%)
result.win_rate            # float: 胜率 (0-1)
result.backtest_rounds     # int: 回测轮数
```

## 错误类型

- `SYNTAX_ERROR` - 语法错误
- `SECURITY_VIOLATION` - 安全违规
- `STRUCTURE_ERROR` - 结构错误
- `RUNTIME_ERROR` - 运行时错误

## 运行测试

```bash
# 完整测试套件
python3 tests/test_strategy_sandbox.py

# 快速示例
python3 examples/sandbox_example.py
```

## 文档

- 完整指南: `docs/SANDBOX_GUIDE.md`
- 实现总结: `docs/SANDBOX_IMPLEMENTATION.md`
- 测试代码: `tests/test_strategy_sandbox.py`

## 支持

项目位置: `/Users/boliu/darwin-workspace/project-darwin`
