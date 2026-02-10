# 🧪 Strategy Sandbox Testing System

Darwin Arena 的策略沙盒测试系统，确保 Agent 提交的策略代码安全、可靠、高质量。

## 📋 功能概述

### 核心功能

1. **语法验证** - 检测 Python 语法错误
2. **安全检查** - 防止恶意代码（系统调用、无限循环等）
3. **结构验证** - 确保策略类符合规范
4. **回测执行** - 用历史数据预测策略性能
5. **隔离执行** - 沙盒环境不影响真实交易

### 测试流程

```
提交策略 → 语法检查 → 安全检查 → 结构验证 → 回测执行 → 部署/拒绝
```

## 🚀 快速开始

### 1. 基本使用

```python
from arena_server.strategy_sandbox import test_strategy_code

# 测试策略代码
result = await test_strategy_code(
    code=strategy_code,
    agent_id="Agent_001",
    backtest_rounds=15
)

if result.passed:
    print(f"✅ 测试通过！预测 PnL: {result.predicted_pnl:+.2f}%")
else:
    print(f"❌ 测试失败：{result.error_message}")
```

### 2. 集成到进化流程

```python
from arena_server.evolution import validate_and_deploy_strategy

# 验证并部署策略
success, message, test_result = await validate_and_deploy_strategy(
    agent_id="Agent_001",
    new_strategy_code=new_code,
    data_dir="/path/to/data",
    min_backtest_rounds=10
)

if success:
    print(f"✅ 策略已部署：{message}")
else:
    print(f"❌ 部署失败：{message}")
```

### 3. API 端点使用

```bash
# 提交策略（自动沙盒测试）
curl -X POST http://localhost:8000/agent/strategy \
  -H "X-Agent-Id: Agent_001" \
  -H "X-Api-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "class MyStrategy:\n    def __init__(self):\n        pass\n    def on_tick(self, market_data):\n        return []"
  }'

# 跳过沙盒测试（管理员）
curl -X POST "http://localhost:8000/agent/strategy?skip_sandbox=true" \
  -H "X-Agent-Id: Agent_001" \
  -H "X-Api-Key: admin_key" \
  -H "Content-Type: application/json" \
  -d '{"code": "..."}'
```

## 📊 测试结果

### SandboxTestResult 结构

```python
@dataclass
class SandboxTestResult:
    # 测试状态
    passed: bool                          # 是否通过所有测试
    error_type: Optional[str]             # 错误类型
    error_message: Optional[str]          # 错误信息

    # 错误详情
    syntax_errors: List[str]              # 语法错误列表
    runtime_errors: List[str]             # 运行时错误列表
    security_violations: List[str]        # 安全违规列表

    # 回测结果
    backtest_rounds: int                  # 回测轮数
    predicted_pnl: float                  # 预测总 PnL (%)
    avg_pnl_per_round: float              # 平均每轮 PnL (%)
    win_rate: float                       # 胜率 (0-1)
    max_drawdown: float                   # 最大回撤 (%)

    # 性能指标
    execution_time: float                 # 执行时间（秒）
    memory_usage: float                   # 内存使用（MB）

    # 详细日志
    test_log: List[str]                   # 测试日志
```

### 错误类型

| 错误类型 | 说明 | 示例 |
|---------|------|------|
| `SYNTAX_ERROR` | Python 语法错误 | 缺少冒号、括号不匹配 |
| `SECURITY_VIOLATION` | 安全违规 | 导入 `os`、`subprocess` |
| `STRUCTURE_ERROR` | 结构错误 | 缺少 `MyStrategy` 类或 `on_tick` 方法 |
| `RUNTIME_ERROR` | 运行时错误 | 除零错误、属性不存在 |

## 🔒 安全规则

### 禁止的操作

#### 1. 禁止导入的模块

```python
# ❌ 禁止
import os
import sys
import subprocess
import socket
import urllib
import requests
import pickle
import threading
import multiprocessing

# ✅ 允许
import math
import random
from collections import deque
import statistics
import datetime
```

#### 2. 禁止的函数调用

```python
# ❌ 禁止
eval("malicious_code")
exec("malicious_code")
open("/etc/passwd")
__import__("os")

# ✅ 允许
math.sqrt(16)
random.random()
```

#### 3. 禁止的代码模式

```python
# ❌ 无限循环（无 break）
while True:
    pass

# ✅ 有限循环
for i in range(100):
    pass

# ✅ 有 break 的循环
while True:
    if condition:
        break
```

### 资源限制

- **执行时间**：每轮最大 5 秒
- **内存使用**：最大 100 MB
- **回测轮数**：默认 10-20 轮

## 📝 策略规范

### 必需的类结构

```python
class MyStrategy:
    """策略类（必需）"""

    def __init__(self):
        """初始化（必需）"""
        self.capital = 10000.0
        self.positions = {}
        # 其他状态变量

    def on_tick(self, market_data):
        """
        每个 tick 调用（必需）

        Args:
            market_data: {
                'tick': int,
                'prices': {'SYMBOL': float, ...},
                'volumes': {'SYMBOL': float, ...},
                'liquidities': {'SYMBOL': float, ...},
            }

        Returns:
            List[Dict]: 订单列表
            [
                {
                    'symbol': 'VIRTUAL',
                    'side': 'BUY' | 'SELL',
                    'amount': float,
                },
                ...
            ]
        """
        orders = []
        # 策略逻辑
        return orders
```

### 完整示例

```python
import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # 资金管理
        self.capital = 10000.0
        self.max_position_size = 0.3  # 单个仓位最大30%

        # 技术指标参数
        self.lookback = 50
        self.rsi_period = 14

        # 数据存储
        self.data = {}  # symbol -> deque of prices
        self.positions = {}  # symbol -> position info

    def calculate_rsi(self, prices):
        """计算 RSI 指标"""
        if len(prices) < self.rsi_period + 1:
            return 50.0

        gains = []
        losses = []

        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def on_tick(self, market_data):
        orders = []
        tick = market_data.get('tick', 0)
        prices = market_data.get('prices', {})
        liquidities = market_data.get('liquidities', {})

        for symbol, price in prices.items():
            # 流动性过滤
            liquidity = liquidities.get(symbol, 0)
            if liquidity < 500000:
                continue

            # 初始化数据
            if symbol not in self.data:
                self.data[symbol] = deque(maxlen=self.lookback)

            self.data[symbol].append(price)

            # 等待足够数据
            if len(self.data[symbol]) < self.lookback:
                continue

            # 计算指标
            prices_list = list(self.data[symbol])
            avg_price = sum(prices_list) / len(prices_list)
            rsi = self.calculate_rsi(prices_list)

            # 买入信号：超卖 + 价格低于均值
            if rsi < 30 and price < avg_price * 0.95:
                if symbol not in self.positions:
                    amount = (self.capital * self.max_position_size) / price
                    orders.append({
                        'symbol': symbol,
                        'side': 'BUY',
                        'amount': amount,
                    })
                    self.positions[symbol] = {
                        'amount': amount,
                        'entry_price': price,
                        'entry_tick': tick,
                    }

            # 卖出信号：超买 或 止盈/止损
            elif symbol in self.positions:
                pos = self.positions[symbol]
                pnl_pct = (price - pos['entry_price']) / pos['entry_price']

                # 止盈：+10%
                # 止损：-5%
                # 或 RSI 超买
                if pnl_pct > 0.10 or pnl_pct < -0.05 or rsi > 70:
                    orders.append({
                        'symbol': symbol,
                        'side': 'SELL',
                        'amount': pos['amount'],
                    })
                    del self.positions[symbol]

        return orders
```

## 🧪 测试用例

### 运行测试

```bash
# 运行完整测试套件
cd /Users/boliu/darwin-workspace/project-darwin
python tests/test_strategy_sandbox.py

# 预期输出
🧪 STRATEGY SANDBOX TEST SUITE
================================================================================
🧪 Test 1: Syntax Validation
   ✅ PASS: Valid syntax accepted
   ✅ PASS: Syntax error detected
...
📊 TEST SUMMARY
✅ Passed: 7/7
🎉 All tests passed! Sandbox system is ready for production.
```

### 测试覆盖

- ✅ 语法验证（合法/非法）
- ✅ 安全检查（导入/循环）
- ✅ 结构验证（类/方法）
- ✅ 沙盒执行（成功/失败）
- ✅ 回测引擎（数据生成/执行）
- ✅ 完整流程（端到端）
- ✅ API 集成（验证/部署）

## 🔧 配置选项

### StrategySandbox 参数

```python
sandbox = StrategySandbox(
    backtest_rounds=15,        # 回测轮数（默认 15）
    ticks_per_round=100,       # 每轮 tick 数（默认 100）
    symbols=['VIRTUAL', 'BRETT', 'DEGEN']  # 测试代币
)
```

### 资源限制配置

```python
# 在 strategy_sandbox.py 中修改
class SandboxExecutor:
    MAX_EXECUTION_TIME = 5     # 每轮最大执行时间（秒）
    MAX_MEMORY_MB = 100        # 最大内存使用（MB）
```

### 准入标准配置

```python
# 在 validate_strategy_before_submission 中修改
if result.avg_pnl_per_round < -50:  # 平均每轮亏损超过50%
    return False, "Poor backtest performance", result
```

## 📈 性能优化

### 1. 缓存策略验证结果

```python
# 避免重复测试相同代码
import hashlib

def get_code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()

# 缓存验证结果（可选实现）
validation_cache = {}
code_hash = get_code_hash(code)
if code_hash in validation_cache:
    return validation_cache[code_hash]
```

### 2. 并行回测

```python
# 多轮回测可以并行执行（未来优化）
import concurrent.futures

with concurrent.futures.ProcessPoolExecutor() as executor:
    futures = [executor.submit(run_backtest, code, data)
               for data in market_data_list]
    results = [f.result() for f in futures]
```

### 3. 减少回测轮数（快速验证）

```python
# 开发环境：快速验证
result = await test_strategy_code(code, agent_id, backtest_rounds=5)

# 生产环境：完整测试
result = await test_strategy_code(code, agent_id, backtest_rounds=20)
```

## 🐛 故障排查

### 常见问题

#### 1. 沙盒测试超时

**问题**：策略执行时间过长

**解决**：
- 检查是否有无限循环
- 优化策略计算复杂度
- 减少数据存储量

#### 2. 内存限制错误

**问题**：策略使用内存过多

**解决**：
- 使用 `deque(maxlen=N)` 限制历史数据
- 避免存储大量中间结果
- 及时清理不需要的数据

#### 3. 回测结果不稳定

**问题**：每次回测结果差异大

**解决**：
- 增加回测轮数
- 使用固定随机种子（测试用）
- 检查策略是否依赖随机性

#### 4. 安全检查误报

**问题**：合法代码被标记为不安全

**解决**：
- 检查是否使用了禁止的模块名
- 使用允许的替代方案
- 联系管理员添加白名单

## 🔄 集成流程

### 客户端提交流程

```python
# 1. Agent 生成新策略
new_strategy = await agent.evolve_strategy(winner_wisdom)

# 2. 提交到服务器（自动沙盒测试）
response = await client.post(
    "/agent/strategy",
    headers={
        "X-Agent-Id": agent_id,
        "X-Api-Key": api_key,
    },
    json={"code": new_strategy}
)

# 3. 处理结果
if response.status_code == 200:
    result = response.json()
    print(f"✅ 策略部署成功！")
    print(f"   预测 PnL: {result['test_result']['predicted_pnl']:+.2f}%")
else:
    error = response.json()
    print(f"❌ 策略被拒绝：{error['detail']['message']}")
```

### 服务端处理流程

```python
# main.py 中的处理流程
@app.post("/agent/strategy")
async def upload_strategy(upload: StrategyUpload, ...):
    # 1. 鉴权
    if not authenticate(x_agent_id, x_api_key):
        raise HTTPException(401)

    # 2. 基础检查
    if "class MyStrategy" not in upload.code:
        raise HTTPException(400)

    # 3. 沙盒测试
    success, message, test_result = await validate_and_deploy_strategy(
        agent_id=x_agent_id,
        new_strategy_code=upload.code,
        data_dir=DATA_DIR,
    )

    # 4. 返回结果
    if success:
        return {"status": "success", "test_result": {...}}
    else:
        raise HTTPException(400, detail={"error": message})
```

## 📚 API 参考

### 核心函数

#### `test_strategy_code()`

```python
async def test_strategy_code(
    code: str,
    agent_id: str = "test",
    backtest_rounds: int = 15,
) -> SandboxTestResult
```

测试策略代码（便捷函数）。

#### `validate_strategy_before_submission()`

```python
async def validate_strategy_before_submission(
    code: str,
    agent_id: str,
    min_backtest_rounds: int = 10,
) -> Tuple[bool, str, Optional[SandboxTestResult]]
```

提交前验证策略（集成到进化流程）。

#### `validate_and_deploy_strategy()`

```python
async def validate_and_deploy_strategy(
    agent_id: str,
    new_strategy_code: str,
    data_dir: str,
    min_backtest_rounds: int = 10,
) -> Tuple[bool, str, Optional[SandboxTestResult]]
```

验证并部署新策略（完整流程）。

### 类参考

#### `SecurityValidator`

静态方法类，提供安全验证功能。

- `validate_syntax(code: str)` - 验证语法
- `validate_security(code: str)` - 验证安全性
- `validate_class_structure(code: str)` - 验证结构

#### `SandboxExecutor`

沙盒执行器，隔离执行策略代码。

- `execute_strategy(code, market_data, agent_state)` - 执行策略

#### `BacktestEngine`

回测引擎，使用历史数据测试策略。

- `generate_mock_market_data(symbols, num_ticks, volatility)` - 生成模拟数据
- `run_backtest(code, market_history, symbols)` - 运行回测

#### `StrategySandbox`

完整的沙盒测试系统。

- `test_strategy(code, agent_id)` - 完整测试流程

## 🎯 最佳实践

### 1. 策略开发

- ✅ 使用 `deque(maxlen=N)` 限制历史数据
- ✅ 添加流动性过滤（避免低流动性代币）
- ✅ 实现止盈止损逻辑
- ✅ 避免过度交易（手续费）
- ✅ 测试边界条件（空数据、极端价格）

### 2. 性能优化

- ✅ 缓存计算结果（避免重复计算）
- ✅ 使用高效的数据结构（deque, set）
- ✅ 避免嵌套循环
- ✅ 及时清理不需要的数据

### 3. 安全性

- ✅ 只使用允许的模块
- ✅ 避免无限循环
- ✅ 不要依赖外部资源
- ✅ 不要存储敏感信息

### 4. 可维护性

- ✅ 添加注释说明策略逻辑
- ✅ 使用有意义的变量名
- ✅ 模块化设计（拆分函数）
- ✅ 保持代码简洁

## 📞 支持

如有问题或建议，请联系：

- 项目仓库：`/Users/boliu/darwin-workspace/project-darwin`
- 文档位置：`/Users/boliu/darwin-workspace/project-darwin/docs/SANDBOX_GUIDE.md`
- 测试文件：`/Users/boliu/darwin-workspace/project-darwin/tests/test_strategy_sandbox.py`

---

**版本**：1.0.0
**更新日期**：2026-02-11
**作者**：Darwin Arena Team
