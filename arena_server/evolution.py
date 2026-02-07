"""
🧬 Evolution Engine - Project Darwin
服务端职责：裁判 + 主持（生成赢家分享、读取赢家策略）
客户端职责：进化（agent 用自己的 LLM 重写策略）
"""

import os
import asyncio
from typing import Dict, Any, List, Optional
from llm_client import call_llm


class MutationEngine:
    """进化引擎：准备赢家上下文，通知客户端自行进化"""

    def __init__(self):
        self.winner_wisdom: str = ""
        self.winner_strategy: str = ""

    def _get_paths(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "..", "data")
        template_dir = os.path.join(base_dir, "..", "agent_template")
        return data_dir, template_dir

    def load_winner_strategy(self, winner_id: str) -> str:
        """读取赢家的策略代码，供广播给客户端"""
        data_dir, template_dir = self._get_paths()

        winner_strategy_path = os.path.join(data_dir, "agents", winner_id, "strategy.py")
        if os.path.exists(winner_strategy_path):
            with open(winner_strategy_path, "r") as f:
                code = f.read()
            print(f"📚 Loaded winner {winner_id}'s strategy for sharing")
            return code

        # Fallback to template
        template_path = os.path.join(template_dir, "strategy.py")
        if os.path.exists(template_path):
            with open(template_path, "r") as f:
                return f.read()

        return ""

    async def generate_winner_sharing(self, winner_id: str, winner_pnl: float, rankings: List) -> str:
        """让 LLM 模拟赢家在议事厅分享经验（服务端裁判/主持功能）"""

        data_dir, _ = self._get_paths()

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
            result = await call_llm(
                messages=[
                    {"role": "system", "content": "你是一个资深的量化交易员，用简洁有力的语言分享经验。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.8,
                timeout=60.0,
            )
            if result:
                return result
        except Exception as e:
            print(f"⚠️ Winner sharing generation failed: {e}")

        return f"作为本轮冠军，我的策略重点是趋势跟踪和严格止损。"


async def run_council_and_evolution(
    engine,  # MatchingEngine
    council,  # Council
    epoch: int,
    winner_id: str,
    losers: List[str],
    broadcast_fn=None,  # async function to broadcast to group
    group_id: int = 0,
) -> Dict[str, Any]:
    """
    议事厅 + 通知客户端进化

    服务端做的事：
    1. 生成赢家分享（LLM 主持）
    2. 记录到议事厅
    3. 广播 mutation_phase 给客户端，让客户端用自己的 LLM 进化

    服务端不再做的事：
    - 替 agent 调 LLM 重写策略（这是客户端的事）
    """
    from council import MessageRole

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

    # 读取赢家策略代码（发给客户端参考）
    winner_strategy = mutation_engine.load_winner_strategy(winner_id)

    # === 第2步: 广播 mutation_phase 给客户端 ===
    print(f"\n🧬 === EVOLUTION PHASE (Client-Side) ===")
    print(f"📋 Losers to evolve: {losers}")
    print(f"📡 Broadcasting mutation_phase to clients...")

    mutation_data = {
        "type": "mutation_phase",
        "epoch": epoch,
        "group_id": group_id,
        "winner_id": winner_id,
        "losers": losers,
        "winner_wisdom": winner_wisdom,
        "winner_strategy": winner_strategy[:3000],  # Cap size for WebSocket
    }

    if broadcast_fn:
        await broadcast_fn(mutation_data)

    print(f"✅ mutation_phase broadcasted. Agents will evolve with their own LLM.")

    return {
        "winner_id": winner_id,
        "winner_wisdom": winner_wisdom,
        "losers_notified": losers,
    }
