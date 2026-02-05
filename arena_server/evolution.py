"""
🧬 Evolution Engine - Project Darwin
输家读赢家分享 → LLM 重写策略代码 → 进化
"""

import os
import re
import json
import asyncio
import traceback
import httpx
from typing import Dict, Any, List, Optional
from config import LLM_BASE_URL, LLM_MODEL, LLM_API_KEY


class MutationEngine:
    """进化引擎：让表现差的 Agent 学习赢家并进化策略"""
    
    def __init__(self, state: Dict = None):
        self.state = state or {}
        self.winner_wisdom: str = ""  # 赢家分享的智慧
        self.winner_strategy: str = ""  # 赢家的策略代码

    def set_winner_context(self, winner_id: str, wisdom: str = ""):
        """设置赢家上下文，供输家学习"""
        self.winner_wisdom = wisdom
        
        # Fix: Use absolute path relative to this file
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "..", "data")
        template_dir = os.path.join(base_dir, "..", "agent_template")

        # 读取赢家的策略代码
        winner_strategy_path = os.path.join(data_dir, "agents", winner_id, "strategy.py")
        if os.path.exists(winner_strategy_path):
            with open(winner_strategy_path, "r") as f:
                self.winner_strategy = f.read()
            print(f"📚 Loaded winner {winner_id}'s strategy for learning")
        else:
            # 用模板
            template_path = os.path.join(template_dir, "strategy.py")
            if os.path.exists(template_path):
                with open(template_path, "r") as f:
                    self.winner_strategy = f.read()

    async def generate_winner_sharing(self, winner_id: str, winner_pnl: float, rankings: List) -> str:
        """让 LLM 模拟赢家在议事厅分享经验"""
        
        # Fix paths
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "..", "data")
        
        # 读取赢家策略
        winner_strategy_path = os.path.join(data_dir, "agents", winner_id, "strategy.py")
        strategy_content = ""
        if os.path.exists(winner_strategy_path):
            with open(winner_strategy_path, "r") as f:
                strategy_content = f.read()
        
        prompt = f"""你是 Project Darwin 竞技场的冠军 AI Agent "{winner_id}"。

你这轮的战绩：
- PnL: +{winner_pnl:.1f}%
- 排名: 第1名

议事厅规则：作为赢家，你需要分享你的交易智慧，帮助其他 Agent 进化。

你的当前策略代码：
```python
{strategy_content[:2000] if strategy_content else '# 基础策略'}
```

请以第一人称分享你的成功经验（200字以内），包括：
1. 你做对了什么
2. 关键的进场/出场时机判断
3. 给其他 Agent 的建议

用中文回答，语气自信但友好："""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{LLM_BASE_URL}/messages",
                    headers={
                        "x-api-key": LLM_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": LLM_MODEL,
                        "system": "你是一个资深的量化交易员，用简洁有力的语言分享经验。",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.8
                    }
                )
                
                if response.status_code == 200:
                    resp_json = response.json()
                    for item in resp_json.get("content", []):
                        if item.get("type") == "text":
                            return item["text"]
                    return resp_json.get("content", [{}])[0].get("text", "")
        except Exception as e:
            print(f"⚠️ Winner sharing generation failed: {e}")
        
        return f"作为本轮冠军，我的策略重点是趋势跟踪和严格止损。"

    async def mutate_agent(self, agent, winner_wisdom: str = "") -> bool:
        """用 LLM 重写 Agent 的策略，基于赢家的智慧"""
        print(f"🧬 Mutating agent {agent.agent_id}...")
        
        async with httpx.AsyncClient(timeout=180.0) as client:
            # 1. 准备 Agent 目录和当前策略
            # Fix: Use absolute path relative to this file, not CWD
            base_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(base_dir, "..", "data")
            
            print(f"[DEBUG] Evolution Base Dir: {base_dir}")
            print(f"[DEBUG] Evolution Data Dir: {os.path.abspath(data_dir)}")
            
            agent_dir = os.path.join(data_dir, "agents", agent.agent_id)
            print(f"[DEBUG] Target Agent Dir: {os.path.abspath(agent_dir)}")
            
            if not os.path.exists(agent_dir):
                os.makedirs(agent_dir, exist_ok=True)
                
            agent_strategy = os.path.join(agent_dir, "strategy.py")
            current_strategy = ""
            if os.path.exists(agent_strategy):
                with open(agent_strategy, "r") as f:
                    current_strategy = f.read()
            else:
                # 从模板复制
                template = os.path.join("..", "agent_template", "strategy.py")
                if os.path.exists(template):
                    with open(template, "r") as f:
                        current_strategy = f.read()
                    with open(agent_strategy, "w") as f:
                        f.write(current_strategy)

            # 2. 构建进化 Prompt（包含赢家智慧）
            prompt = f"""你是 Project Darwin 的进化引擎。

# 🎯 任务
重写 Agent "{agent.agent_id}" 的交易策略代码，帮助它在下一轮竞技中表现更好。

# 📊 当前状态
- 当前余额: ${agent.balance:.2f} (初始 $1000)
- PnL: {((agent.balance - 1000) / 1000 * 100):.1f}%
- 状态: 表现不佳，需要进化

# 🏆 赢家分享的智慧
{winner_wisdom if winner_wisdom else '(赢家未分享)'}

# 📝 赢家的策略参考
```python
{self.winner_strategy[:1500] if self.winner_strategy else '# 无可参考策略'}
```

# 📝 当前失败的策略
```python
{current_strategy[:1500] if current_strategy else '# 空策略'}
```

# ⚡ 进化要求
1. 吸收赢家的智慧和策略精髓
2. 但要有自己的独特变异（避免同质化）
3. 增强风控（止损、仓位管理）
4. 代码必须完整可运行

只输出完整的 Python 代码，包含所有 import："""

            try:
                target_url = f"{LLM_BASE_URL}/messages"
                print(f"📡 Calling LLM for {agent.agent_id}...")
                
                response = await client.post(
                    target_url,
                    headers={
                        "x-api-key": LLM_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": LLM_MODEL,
                        "system": "你是世界级的量化交易工程师。只输出完整的 Python 策略代码，不要解释。",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 4096,
                        "temperature": 0.7
                    }
                )
                
                if response.status_code != 200:
                    print(f"❌ LLM Error: {response.status_code} - {response.text}")
                    return False
                
                resp_json = response.json()
                
                # 解析响应
                new_code = ""
                for item in resp_json.get("content", []):
                    if item.get("type") == "text" and "text" in item:
                        new_code = item["text"]
                        break
                
                if not new_code:
                    print(f"❌ No code in response")
                    return False
                
                # 清理 markdown
                if "```python" in new_code:
                    match = re.search(r"```python\n(.*?)\n```", new_code, re.DOTALL)
                    if match:
                        new_code = match.group(1)
                elif "```" in new_code:
                    match = re.search(r"```\n(.*?)\n```", new_code, re.DOTALL)
                    if match:
                        new_code = match.group(1)

                # 保存新策略
                backup_path = agent_strategy + ".bak"
                if os.path.exists(agent_strategy):
                    os.rename(agent_strategy, backup_path)
                with open(agent_strategy, "w") as f:
                    f.write(new_code)
                    
                print(f"✅ Agent {agent.agent_id} evolved successfully!")
                return True

            except Exception as e:
                traceback.print_exc()
                return False


async def run_council_and_evolution(
    engine,  # MatchingEngine
    council,  # Council
    epoch: int,
    winner_id: str,
    losers: List[str]
) -> Dict[str, bool]:
    """
    完整的议事厅 + 进化流程
    1. 赢家分享智慧
    2. 输家学习并进化
    """
    from council import MessageRole
    
    results = {}
    mutation_engine = MutationEngine()
    
    # 获取排行榜
    rankings = engine.get_leaderboard()
    winner_pnl = next((r[1] for r in rankings if r[0] == winner_id), 0)
    
    # === 第1步: 赢家分享 ===
    print(f"\n🏛️ === COUNCIL SESSION (Epoch {epoch}) ===")
    print(f"🏆 Winner: {winner_id} (+{winner_pnl:.1f}%)")
    
    winner_wisdom = await mutation_engine.generate_winner_sharing(winner_id, winner_pnl, rankings)
    print(f"\n💬 {winner_id} 分享:\n{winner_wisdom}\n")
    
    # 记录到议事厅
    await council.submit_message(
        epoch=epoch,
        agent_id=winner_id,
        role=MessageRole.WINNER,
        content=winner_wisdom
    )
    
    # 设置赢家上下文供进化使用
    mutation_engine.set_winner_context(winner_id, winner_wisdom)
    
    # === 第2步: 输家进化 ===
    print(f"\n🧬 === EVOLUTION PHASE ===")
    print(f"📋 Losers to evolve: {losers}")
    
    for loser_id in losers:
        agent = engine.accounts.get(loser_id)
        if agent:
            success = await mutation_engine.mutate_agent(agent, winner_wisdom)
            results[loser_id] = success
            
            # 记录输家的"反思"
            if success:
                await council.submit_message(
                    epoch=epoch,
                    agent_id=loser_id,
                    role=MessageRole.LOSER,
                    content=f"我学习了 {winner_id} 的策略并进化了我的代码。"
                )
    
    print(f"\n✅ Council & Evolution completed!")
    print(f"📊 Results: {results}")
    
    return results
