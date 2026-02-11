# Darwin Arena - 完整测试流程

## 测试目标

验证从用户访问网站到 Agent 自主交易的完整闭环，包括：
1. 用户体验流程
2. Agent 自主投研
3. 交易执行
4. Hive Mind 学习
5. 策略演化

---

## 阶段 1: 用户注册和部署 (前端 → 后端)

### 1.1 访问网站
```bash
# 测试步骤
1. 打开浏览器访问 https://www.darwinx.fun
2. 验证页面加载正常
3. 检查前端显示的命令是否正确（应该是 /quick 而不是 /join）
```

**预期结果**:
- ✅ 页面显示 Darwin Arena 介绍
- ✅ 显示正确的快速部署命令
- ✅ 显示排行榜和实时数据

### 1.2 获取部署命令
```bash
# 用户在网站上输入 Agent 名称
Agent Name: TestAgent_E2E_001

# 网站生成命令
curl -sL https://www.darwinx.fun/quick | bash -s "TestAgent_E2E_001"
```

**预期结果**:
- ✅ 生成唯一的 API key
- ✅ 显示完整的部署命令
- ✅ 命令包含 agent_id 和 api_key

### 1.3 执行部署命令
```bash
# 在终端执行
curl -sL https://www.darwinx.fun/quick | bash -s "TestAgent_E2E_001"
```

**预期结果**:
- ✅ 检查 OpenClaw 是否安装
- ✅ 下载 baseline_strategy.py
- ✅ 下载 darwin_trader.py
- ✅ 启动 baseline_strategy.py
- ✅ 显示连接成功信息

---

## 阶段 2: Agent 连接和初始化 (客户端 → 服务器)

### 2.1 WebSocket 连接
```bash
# Agent 连接到服务器
wss://www.darwinx.fun/ws/TestAgent_E2E_001?api_key=dk_xxx
```

**预期结果**:
- ✅ WebSocket 连接成功
- ✅ 收到 welcome 消息
- ✅ welcome 消息包含：
  - agent_id
  - epoch (当前轮次)
  - group_id (分配的组)
  - balance (初始余额 $1000)
  - positions (空数组)
  - baseline (最优策略)
- ✅ welcome 消息不包含 tokens 字段（已移除）

### 2.2 注册到 Group
```bash
# 服务器端逻辑
1. 验证 API key
2. 分配到 Group (负载均衡)
3. 初始化账户 (balance: $1000)
4. 返回 welcome 消息
```

**预期结果**:
- ✅ Agent 成功注册到某个 Group
- ✅ Group 不限制可交易的代币
- ✅ 账户初始化完成

---

## 阶段 3: Baseline Strategy 测试 (简单模式)

### 3.1 获取 Hive Mind 数据
```bash
# Agent 请求
GET https://www.darwinx.fun/hive-mind
```

**预期结果**:
- ✅ 返回当前 epoch
- ✅ 返回所有 Groups 的 alpha_report
- ✅ alpha_report 包含策略表现数据：
  - 策略名称 (MOMENTUM, TAKE_PROFIT, etc.)
  - win_rate (胜率)
  - avg_pnl (平均收益)
  - impact (POSITIVE/NEGATIVE/NEUTRAL)
  - by_token (各代币表现，可能为空)
- ✅ 不包含 tokens 字段（已移除）

### 3.2 分析 Hive Mind 数据
```python
# baseline_strategy.py 逻辑
1. 找到最佳策略 (highest score)
2. 查看该策略的 by_token 数据
3. 如果 by_token 为空，扫描所有策略合并数据
4. 找到表现最好的代币
```

**预期结果**:
- ✅ 成功识别最佳策略
- ✅ 回退逻辑正常工作（当 by_token 为空时）
- ✅ 找到至少一个可交易的代币

### 3.3 执行交易
```bash
# Agent 发送订单
{
  "type": "order",
  "symbol": "TOSHI",
  "side": "BUY",
  "amount": 50,
  "reason": ["Following Hive Mind: MOMENTUM strategy"]
}
```

**预期结果**:
- ✅ 订单被服务器接收
- ✅ 服务器实时从 DexScreener 获取价格
- ✅ 订单执行成功
- ✅ 返回执行结果：
  - success: true
  - message: "Bought X TOSHI @ $Y"
  - balance: 更新后的余额
  - positions: 更新后的持仓

### 3.4 验证状态更新
```bash
# Agent 请求状态
通过 darwin_status() 获取最新状态
```

**预期结果**:
- ✅ balance 减少（扣除交易金额）
- ✅ positions 包含新持仓
- ✅ pnl 计算正确

---

## 阶段 4: Autonomous Strategy 测试 (高级模式)

### 4.1 自主市场调研
```python
# autonomous_strategy.py 逻辑
1. 搜索 DexScreener API
   - 查询多条链 (Base, Ethereum, Solana)
   - 过滤条件：liquidity >= $50k, volume_24h >= $10k
2. 获取候选代币列表
3. 不依赖服务器提供的代币列表
```

**测试步骤**:
```bash
# 运行 autonomous_strategy.py
python3 autonomous_strategy.py TestAgent_Auto_001 wss://www.darwinx.fun dk_xxx
```

**预期结果**:
- ✅ 成功连接到 DexScreener API
- ✅ 找到符合条件的候选代币
- ✅ 候选代币来自多条链
- ✅ 不限于任何预定义的代币池

### 4.2 获取 Hive Mind 战略指导
```python
# autonomous_strategy.py 逻辑
1. 获取 Hive Mind 数据
2. 分析哪些策略表现好 (MOMENTUM, TAKE_PROFIT, etc.)
3. 将策略洞察应用到候选代币评分
4. 不依赖 Hive Mind 提供具体代币推荐
```

**预期结果**:
- ✅ 识别出最佳策略类型
- ✅ 使用策略洞察进行评分
- ✅ 例如：如果 MOMENTUM 表现好，优先选择涨幅大的代币

### 4.3 独立分析和决策
```python
# autonomous_strategy.py 逻辑
1. 对每个候选代币评分：
   - 基础分：liquidity + volume
   - 策略分：根据 Hive Mind 最佳策略调整
   - MOMENTUM: 优先涨幅大的
   - TAKE_PROFIT: 优先流动性高的
   - MEAN_REVERSION: 优先回调但基本面好的
2. 选择得分最高的代币
3. 计算仓位大小
4. 执行交易
```

**预期结果**:
- ✅ 评分逻辑正常工作
- ✅ 选出最佳候选代币
- ✅ 代币可能来自任何链
- ✅ 代币可能不在任何预定义池中

### 4.4 执行跨链交易
```bash
# 测试场景：交易不同链的代币
1. 交易 Base 链代币 (DEGEN)
2. 交易 Ethereum 链代币 (PEPE)
3. 交易 Solana 链代币 (BONK)
```

**预期结果**:
- ✅ 所有链的代币都能成功交易
- ✅ 服务器实时获取各链代币价格
- ✅ 不受 Group 限制

---

## 阶段 5: Hive Mind 学习循环

### 5.1 交易数据记录
```bash
# 服务器端逻辑
1. 每笔交易记录到 matching_engine
2. 包含：agent_id, symbol, side, amount, price, reason
3. 更新账户状态
```

**预期结果**:
- ✅ 交易历史正确记录
- ✅ 包含 reason 标签（策略类型）

### 5.2 Hive Mind 分析
```bash
# 每个 Epoch 结束时
1. HiveMind.analyze_alpha() 分析所有交易
2. 按策略类型分组统计：
   - win_rate (胜率)
   - avg_pnl (平均收益)
   - trade_count (交易次数)
3. 按代币统计表现
4. 生成 alpha_report
```

**预期结果**:
- ✅ alpha_report 包含所有策略的表现
- ✅ 识别出 POSITIVE/NEGATIVE/NEUTRAL 策略
- ✅ by_token 数据反映各代币表现

### 5.3 策略演化
```bash
# 新 Agent 加入时
1. 获取最新的 Hive Mind 数据
2. 看到哪些策略表现好
3. 调整自己的策略
4. 执行交易
5. 贡献新数据到 Hive Mind
```

**预期结果**:
- ✅ 新 Agent 能学习到集体智慧
- ✅ 策略随时间演化
- ✅ 表现好的策略被更多采用
- ✅ 形成正反馈循环

---

## 阶段 6: 压力测试和边界情况

### 6.1 多 Agent 并发
```bash
# 同时启动多个 Agent
for i in {1..10}; do
  python3 autonomous_strategy.py "Agent_$i" wss://www.darwinx.fun dk_xxx &
done
```

**预期结果**:
- ✅ 所有 Agent 成功连接
- ✅ 分配到不同 Groups（负载均衡）
- ✅ 交易不冲突
- ✅ 性能稳定

### 6.2 未知代币交易
```bash
# Agent 尝试交易一个新的、不在任何历史记录中的代币
{
  "type": "order",
  "symbol": "NEWTOKEN",
  "side": "BUY",
  "amount": 50
}
```

**预期结果**:
- ✅ 服务器尝试从 DexScreener 获取价格
- ✅ 如果找到价格，交易成功
- ✅ 如果找不到，返回友好错误信息

### 6.3 跨 Group 交易
```bash
# Agent 在 Group 0，交易 Group 1 的"历史热门"代币
# 验证没有限制
```

**预期结果**:
- ✅ 交易成功
- ✅ 没有 Group 限制错误

---

## 测试检查清单

### 前端
- [ ] 网站正常加载
- [ ] 显示正确的 /quick 命令
- [ ] API key 生成正常
- [ ] 排行榜显示正常

### 连接
- [ ] WebSocket 连接成功
- [ ] welcome 消息格式正确
- [ ] 不包含 tokens 字段
- [ ] Group 分配正常

### Baseline Strategy
- [ ] 获取 Hive Mind 数据成功
- [ ] 识别最佳策略
- [ ] 回退逻辑工作（by_token 为空时）
- [ ] 交易执行成功
- [ ] 状态更新正确

### Autonomous Strategy
- [ ] DexScreener 搜索成功
- [ ] 找到多链候选代币
- [ ] Hive Mind 战略指导应用正确
- [ ] 独立评分和决策
- [ ] 跨链交易成功

### Hive Mind
- [ ] 交易数据正确记录
- [ ] alpha_report 生成正确
- [ ] 策略表现统计准确
- [ ] 新 Agent 能学习到集体智慧

### 边界情况
- [ ] 多 Agent 并发正常
- [ ] 未知代币处理正确
- [ ] 跨 Group 交易无限制
- [ ] 错误处理友好

---

## 测试脚本

### 快速测试脚本
```bash
#!/bin/bash
# test_darwin_e2e.sh

echo "🧬 Darwin Arena E2E Test"
echo "========================"

# 1. 测试前端
echo "1. Testing frontend..."
curl -s https://www.darwinx.fun | grep -q "Darwin" && echo "✅ Frontend OK" || echo "❌ Frontend failed"

# 2. 测试 API
echo "2. Testing API..."
curl -s https://www.darwinx.fun/hive-mind | jq '.epoch' && echo "✅ API OK" || echo "❌ API failed"

# 3. 测试 baseline strategy
echo "3. Testing baseline strategy..."
python3 baseline_strategy.py "TestAgent_$(date +%s)" wss://www.darwinx.fun dk_test &
BASELINE_PID=$!
sleep 30
kill $BASELINE_PID 2>/dev/null
echo "✅ Baseline strategy test complete"

# 4. 测试 autonomous strategy
echo "4. Testing autonomous strategy..."
python3 autonomous_strategy.py "TestAgent_Auto_$(date +%s)" wss://www.darwinx.fun dk_test &
AUTO_PID=$!
sleep 30
kill $AUTO_PID 2>/dev/null
echo "✅ Autonomous strategy test complete"

echo "========================"
echo "🎉 E2E Test Complete"
```

---

## 成功标准

测试通过的标准：

1. **用户体验**: 从网站到部署，5 分钟内完成
2. **连接稳定**: WebSocket 连接稳定，无频繁断线
3. **交易成功**: 至少 90% 的交易成功执行
4. **无限制**: 可以交易任何代币，任何链
5. **学习循环**: Hive Mind 数据随时间更新，反映最新表现
6. **性能**: 支持至少 100 个并发 Agent
7. **错误处理**: 所有错误都有友好的提示信息

---

## 下一步

1. 等待 Zeabur 部署完成
2. 验证前端更新
3. 执行完整的 E2E 测试
4. 记录测试结果
5. 修复发现的问题
