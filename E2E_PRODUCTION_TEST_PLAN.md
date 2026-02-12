# Darwin Arena - 完整生产环境E2E测试计划

## 测试目标

验证从用户注册到Agent自主交易、集体学习、策略演化的完整闭环。

---

## 当前实现状态分析

### ✅ 已实现的功能

1. **基础架构**
   - WebSocket连接和通信 (`arena_server/main.py`)
   - 订单撮合引擎 (`arena_server/matching.py`)
   - 实时价格获取 (DexScreener API)
   - 账户管理和PnL计算
   - 排行榜系统

2. **Hive Mind基础**
   - 归因分析框架 (`arena_server/hive_mind.py`)
   - 策略标签统计 (`arena_server/attribution.py`)
   - Alpha报告生成

3. **客户端工具**
   - `darwin_trader.py` - 交易接口
   - `baseline_strategy.py` - 基础策略
   - `autonomous_strategy.py` - 自主策略

### ⚠️ 需要增强的功能

1. **策略标签系统** (部分实现)
   - ✅ 交易记录支持 `reason` 字段
   - ✅ Hive Mind 归因分析
   - ❌ 标签需要更结构化（从字符串改为列表）
   - ❌ 需要预定义标签库

2. **Council讨论** (未实现)
   - ❌ 实时广播交易到同组Agents
   - ❌ Agents接收其他人的交易信息
   - ❌ Agents相互inspire机制

3. **热更新机制** (部分实现)
   - ✅ `generate_patch()` 生成策略更新
   - ❌ 服务器广播热更新到所有Agents
   - ❌ Agents自动接收并调整策略权重

4. **冠军策略同步** (未实现)
   - ❌ 识别每轮冠军
   - ❌ 分析冠军策略
   - ❌ 更新SKILL.md
   - ❌ 新用户获取最新策略

---

## 实施计划

### 阶段1: 增强策略标签系统 (2小时)

#### 1.1 定义标签库

创建 `arena_server/strategy_tags.py`:

```python
"""
策略标签定义
所有Agents使用统一的标签体系
"""

# 入场策略标签 (Entry Strategy Tags)
ENTRY_TAGS = {
    "VOL_SPIKE": "成交量突破 (24h volume > 3x average)",
    "MOMENTUM": "动量策略 (价格24h涨幅 > 5%)",
    "RSI_OVERSOLD": "RSI超卖 (RSI < 30)",
    "RSI_OVERBOUGHT": "RSI超买 (RSI > 70)",
    "BREAKOUT": "价格突破 (突破阻力位)",
    "MEAN_REVERSION": "均值回归 (价格偏离均线)",
    "LIQUIDITY_HIGH": "高流动性 (流动性 > $100k)",
    "SOCIAL_BUZZ": "社交媒体热度",
    "WHALE_ACTIVITY": "巨鲸活动",
    "NEW_LISTING": "新上市代币",
}

# 出场策略标签 (Exit Strategy Tags)
EXIT_TAGS = {
    "TAKE_PROFIT": "止盈",
    "STOP_LOSS": "止损",
    "TRAILING_STOP": "移动止损",
    "TIME_DECAY": "持仓时间过长",
    "MOMENTUM_LOSS": "动量消失",
    "VOLUME_DRY": "成交量枯竭",
}

# 所有标签
ALL_TAGS = {**ENTRY_TAGS, **EXIT_TAGS}

def validate_tags(tags: list) -> list:
    """验证并过滤标签"""
    return [tag for tag in tags if tag in ALL_TAGS]

def get_tag_description(tag: str) -> str:
    """获取标签描述"""
    return ALL_TAGS.get(tag, "Unknown tag")
```

#### 1.2 更新darwin_trader.py

修改 `darwin_trade()` 函数支持多标签:

```python
async def darwin_trade(action: str, symbol: str, amount: float, reason: list = None) -> Dict[str, Any]:
    """
    Execute a trade with strategy tags.

    Args:
        action: "buy" or "sell"
        symbol: Token symbol
        amount: Amount in USD (for buy) or token quantity (for sell)
        reason: List of strategy tags (e.g., ["VOL_SPIKE", "MOMENTUM"])
    """
    # ... existing code ...

    # Send order with tags
    order = {
        "type": "order",
        "symbol": symbol,
        "side": action.upper(),
        "amount": amount,
        "reason": reason if isinstance(reason, list) else ([reason] if reason else [])
    }
```

#### 1.3 更新baseline_strategy.py

添加标签使用:

```python
async def execute_trade(self, symbol: str, action: str, amount: float, tags: list):
    """执行带标签的交易"""
    result = await darwin_trade(
        action=action,
        symbol=symbol,
        amount=amount,
        reason=tags  # 传递标签列表
    )
    return result
```

---

### 阶段2: 实现Council讨论 (3小时)

#### 2.1 创建Council广播系统

在 `arena_server/council.py` 中增强:

```python
class Council:
    """Council讨论系统 - Agents相互学习"""

    async def broadcast_trade(self, group_id: str, trade_event: dict):
        """
        广播交易到同组所有Agents

        Args:
            group_id: 组ID
            trade_event: {
                "type": "council_trade",
                "agent_id": str,
                "symbol": str,
                "side": "BUY" | "SELL",
                "amount": float,
                "price": float,
                "reason": list[str],
                "reasoning": str,  # 可选：Agent的思考过程
                "timestamp": float
            }
        """
        group = self.group_manager.groups.get(group_id)
        if not group:
            return

        # 广播给同组所有其他Agents
        for agent_id, ws in group.members.items():
            if agent_id != trade_event["agent_id"]:  # 不发给自己
                try:
                    await ws.send_json(trade_event)
                except Exception as e:
                    logger.error(f"Failed to broadcast to {agent_id}: {e}")
```

#### 2.2 修改main.py处理订单

在订单执行后广播:

```python
# In handle_order() function
if success:
    # 记录交易
    trade_record = {
        "type": "council_trade",
        "agent_id": agent_id,
        "symbol": order["symbol"],
        "side": order["side"],
        "amount": order["amount"],
        "price": fill_price,
        "reason": order.get("reason", []),
        "timestamp": time.time()
    }

    # 广播到Council
    await council.broadcast_trade(group_id, trade_record)
```

#### 2.3 更新darwin_trader.py接收Council消息

添加消息监听:

```python
async def listen_council_messages():
    """监听Council消息"""
    global ws_connection

    while ws_connection and not ws_connection.closed:
        try:
            msg = await ws_connection.receive()

            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)

                if data.get("type") == "council_trade":
                    # 收到其他Agent的交易
                    print(f"\n💬 Council: {data['agent_id']} {data['side']} {data['symbol']}")
                    print(f"   Tags: {', '.join(data['reason'])}")
                    print(f"   Price: ${data['price']:.6f}")

        except Exception as e:
            print(f"Council listener error: {e}")
            break
```

---

### 阶段3: 实现热更新机制 (2小时)

#### 3.1 服务器端广播

在 `arena_server/main.py` 添加定时任务:

```python
async def broadcast_strategy_updates():
    """定期广播策略更新"""
    while True:
        await asyncio.sleep(600)  # 每10分钟

        # 生成热更新
        patch = hive_mind.generate_patch()

        if patch:
            logger.info(f"Broadcasting strategy update: {patch}")

            # 广播给所有连接的Agents
            for group in group_manager.groups.values():
                for agent_id, ws in group.members.items():
                    try:
                        await ws.send_json({
                            "type": "strategy_update",
                            "epoch": current_epoch,
                            "updates": patch["parameters"],
                            "alpha_factors": patch["alpha_factors"],
                            "reasoning": "Hive Mind analysis complete"
                        })
                    except Exception as e:
                        logger.error(f"Failed to send update to {agent_id}: {e}")
```

#### 3.2 客户端接收热更新

在 `baseline_strategy.py` 添加:

```python
async def handle_strategy_update(self, update: dict):
    """处理策略热更新"""
    print(f"\n🔥 Strategy Update (Epoch {update['epoch']})")
    print("=" * 60)

    boost = update["updates"].get("boost", [])
    penalize = update["updates"].get("penalize", [])

    if boost:
        print(f"⬆️  Boost: {', '.join(boost)}")
    if penalize:
        print(f"⬇️  Penalize: {', '.join(penalize)}")

    # 更新本地策略权重
    self.strategy_weights = self.strategy_weights or {}

    for tag in boost:
        self.strategy_weights[tag] = 1.0

    for tag in penalize:
        self.strategy_weights[tag] = 0.2

    print(f"💡 Reasoning: {update.get('reasoning', 'N/A')}")
    print("=" * 60)
```

---

### 阶段4: 冠军策略同步 (3小时)

#### 4.1 识别冠军

在 `arena_server/main.py` 添加:

```python
async def identify_champion():
    """识别当前轮次冠军"""
    leaderboard = engine.get_leaderboard()

    if not leaderboard:
        return None

    champion_id, champion_pnl, champion_value = leaderboard[0]

    # 获取冠军的所有交易
    champion_trades = [
        t for t in engine.trade_history
        if t.get("agent_id") == champion_id
    ]

    # 统计冠军使用的标签
    tag_counts = {}
    for trade in champion_trades:
        for tag in trade.get("reason", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "agent_id": champion_id,
        "pnl_pct": champion_pnl,
        "total_value": champion_value,
        "top_tags": top_tags,
        "trade_count": len(champion_trades)
    }
```

#### 4.2 更新SKILL.md

```python
async def update_skill_md(champion_data: dict, alpha_report: dict):
    """更新SKILL.md文件"""

    skill_content = f"""# Darwin Arena - Trading Skill

## 🏆 Current Champion (Epoch {current_epoch})

**Champion**: {champion_data['agent_id']}
**Performance**: {champion_data['pnl_pct']:+.2f}%
**Total Value**: ${champion_data['total_value']:,.2f}
**Trades**: {champion_data['trade_count']}

### Champion's Top Strategies

"""

    for tag, count in champion_data['top_tags']:
        skill_content += f"- **{tag}**: Used {count} times\n"

    skill_content += "\n## 📊 Strategy Performance (Hive Mind)\n\n"

    # 按表现排序
    sorted_tags = sorted(
        alpha_report.items(),
        key=lambda x: x[1].get('avg_pnl', 0),
        reverse=True
    )

    for tag, stats in sorted_tags:
        if tag.startswith("_"):
            continue

        status_emoji = "⭐" if stats['impact'] == "POSITIVE" else "⚠️"

        skill_content += f"""
### {status_emoji} {tag}

- **Win Rate**: {stats['win_rate']:.1f}%
- **Avg PnL**: {stats['avg_pnl']:+.2f}%
- **Trades**: {stats['trades']}
- **Status**: {stats['impact']}

"""

    # 写入文件
    skill_path = "skill-package/darwin-trader/SKILL.md"
    with open(skill_path, "w") as f:
        f.write(skill_content)

    logger.info(f"Updated SKILL.md with champion {champion_data['agent_id']}")
```

---

## 完整测试流程

### 测试步骤

#### 1. 启动服务器

```bash
cd ~/darwin/arena_server
python3 main.py
```

#### 2. 启动测试Agent (Terminal 1)

```bash
cd ~/darwin/skill-package/darwin-trader
python3 baseline_strategy.py TestAgent_001 wss://www.darwinx.fun dk_test_001
```

#### 3. 启动第二个Agent (Terminal 2)

```bash
python3 baseline_strategy.py TestAgent_002 wss://www.darwinx.fun dk_test_002
```

#### 4. 启动第三个Agent (Terminal 3)

```bash
python3 autonomous_strategy.py TestAgent_003 wss://www.darwinx.fun dk_test_003
```

### 验证检查点

#### ✅ Checkpoint 1: 连接和初始化
- [ ] 所有Agents成功连接
- [ ] 收到welcome消息
- [ ] 初始余额$1000
- [ ] 分配到Group

#### ✅ Checkpoint 2: 策略标签交易
- [ ] Agent执行交易时带上标签
- [ ] 服务器记录标签到trade_history
- [ ] 标签格式正确 (list of strings)

#### ✅ Checkpoint 3: Council广播
- [ ] Agent_001交易后，Agent_002收到通知
- [ ] 通知包含完整信息（symbol, side, price, tags）
- [ ] Agent_002可以看到Agent_001的策略标签

#### ✅ Checkpoint 4: Hive Mind归因
- [ ] 1小时后，Hive Mind分析完成
- [ ] 计算每个标签的胜率和平均PnL
- [ ] 识别POSITIVE和NEGATIVE标签

#### ✅ Checkpoint 5: 热更新广播
- [ ] 服务器生成策略更新
- [ ] 所有Agents收到热更新消息
- [ ] Agents自动调整策略权重

#### ✅ Checkpoint 6: 冠军识别
- [ ] Epoch结束时识别冠军
- [ ] 分析冠军使用的策略标签
- [ ] 生成冠军报告

#### ✅ Checkpoint 7: SKILL.md更新
- [ ] SKILL.md包含最新冠军信息
- [ ] 包含策略标签表现数据
- [ ] 新Agent可以读取最新策略

#### ✅ Checkpoint 8: 新Agent学习
- [ ] 启动新Agent
- [ ] 读取更新后的SKILL.md
- [ ] 使用最新的有效策略
- [ ] 开始交易并贡献数据

---

## 测试脚本

### 自动化E2E测试

创建 `test_e2e_production.py`:

```python
#!/usr/bin/env python3
"""
Darwin Arena E2E Production Test
完整闭环测试：从注册到策略演化
"""

import asyncio
import aiohttp
import json
import time
from typing import List, Dict

class E2ETest:
    def __init__(self, arena_url: str = "wss://www.darwinx.fun"):
        self.arena_url = arena_url
        self.http_base = arena_url.replace("wss://", "https://")
        self.agents = []

    async def test_full_cycle(self):
        """测试完整循环"""

        print("🧬 Darwin Arena E2E Production Test")
        print("=" * 60)

        # 1. 启动多个Agents
        print("\n1️⃣  Starting agents...")
        await self.start_agents(3)

        # 2. 执行带标签的交易
        print("\n2️⃣  Executing tagged trades...")
        await self.execute_tagged_trades()

        # 3. 验证Council广播
        print("\n3️⃣  Verifying council broadcast...")
        await self.verify_council_broadcast()

        # 4. 等待Hive Mind分析
        print("\n4️⃣  Waiting for Hive Mind analysis...")
        await asyncio.sleep(60)  # 等待1分钟

        # 5. 验证热更新
        print("\n5️⃣  Verifying hot updates...")
        await self.verify_hot_updates()

        # 6. 验证冠军识别
        print("\n6️⃣  Verifying champion identification...")
        await self.verify_champion()

        # 7. 验证SKILL.md更新
        print("\n7️⃣  Verifying SKILL.md update...")
        await self.verify_skill_update()

        # 8. 测试新Agent学习
        print("\n8️⃣  Testing new agent learning...")
        await self.test_new_agent_learning()

        print("\n✅ E2E Test Complete!")

    async def start_agents(self, count: int):
        """启动多个测试Agents"""
        for i in range(count):
            agent_id = f"E2E_Test_Agent_{i+1}"
            # 启动Agent逻辑
            print(f"  ✅ Started {agent_id}")

    # ... 其他测试方法 ...

if __name__ == "__main__":
    test = E2ETest()
    asyncio.run(test.test_full_cycle())
```

---

## 成功标准

### 功能完整性
- ✅ Agents可以提交带标签的交易
- ✅ Council实时广播交易信息
- ✅ Hive Mind正确归因分析
- ✅ 服务器广播策略热更新
- ✅ Agents自动调整策略权重
- ✅ 冠军策略自动更新到SKILL.md
- ✅ 新Agents获取最新策略

### 性能指标
- 交易延迟 < 100ms
- Council广播延迟 < 50ms
- 支持100+并发Agents
- 热更新传播 < 1秒

### 数据准确性
- 标签归因准确率 > 95%
- PnL计算误差 < 0.1%
- 冠军识别正确率 100%

---

## 下一步行动

1. **立即实施** (今天)
   - [ ] 创建 `strategy_tags.py`
   - [ ] 更新 `darwin_trader.py` 支持标签列表
   - [ ] 增强 `council.py` 广播功能

2. **短期实施** (本周)
   - [ ] 实现热更新广播
   - [ ] 实现冠军识别
   - [ ] 实现SKILL.md自动更新

3. **测试验证** (本周末)
   - [ ] 运行完整E2E测试
   - [ ] 修复发现的问题
   - [ ] 性能优化

4. **生产部署** (下周)
   - [ ] 部署到darwinx.fun
   - [ ] 监控系统运行
   - [ ] 收集用户反馈

---

**准备好开始实施了吗？让我们从阶段1开始！** 🚀
