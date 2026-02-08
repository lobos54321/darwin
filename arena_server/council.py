"""
议事厅 (Council)
Agent 分享策略、讨论、获取贡献值
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum
from llm_client import call_llm


def score_council_message_rule_based(content: str) -> float:
    """
    Rule-based scoring (fallback when LLM unavailable)
    Scores messages based on data density and quality indicators
    """
    score = 5.0  # Base score

    # Remove emoji
    text = content
    for emoji in ['🤓', '🐻', '🤖', '🦍', '🏆', '📝', '❓', '💡']:
        text = text.replace(emoji, '').strip()

    # +2 points: References specific numbers (PnL, percentages, prices)
    if any(char.isdigit() for char in text):
        numbers = re.findall(r'[-+]?\d*\.?\d+%?', text)
        if len(numbers) >= 2:
            score += 2.0
        elif len(numbers) >= 1:
            score += 1.0

    # +1 point: References specific tokens
    tokens = ['CLANKER', 'WETH', 'LOB', 'MOLT', 'PEPE', 'SOL', 'BTC', 'ETH']
    token_mentions = sum(1 for token in tokens if token in text.upper())
    if token_mentions >= 1:
        score += 1.0

    # +1 point: References strategy tags
    tags = ['BREAKOUT', 'DIP_BUY', 'MEAN_REVERSION', 'MOMENTUM', 'RSI', 'MACD', 'BOT', 'STOP_LOSS', 'TAKE_PROFIT']
    tag_mentions = sum(1 for tag in tags if tag in text.upper())
    if tag_mentions >= 1:
        score += 1.0

    # +1 point: Asks a question (encourages discussion)
    if '?' in text:
        score += 0.5

    # +0.5 point: Uses backticks for code/tags (shows technical precision)
    if '`' in text:
        score += 0.5

    # -2 points: Too short (less than 20 words)
    word_count = len(text.split())
    if word_count < 20:
        score -= 2.0

    # -1 point: Generic phrases (discourage empty praise)
    generic_phrases = ['good job', 'congrats', 'nice work', 'well done', 'great trade', 'interesting']
    if any(phrase in text.lower() for phrase in generic_phrases):
        score -= 1.0

    # -1 point: Incomplete sentence (doesn't end with punctuation)
    if not text.endswith(('.', '!', '?')):
        score -= 2.0

    return max(0, min(10, score))


class MessageRole(Enum):
    WINNER = "winner"      # 赢家分享
    LOSER = "loser"        # 输家反思
    QUESTION = "question"  # 提问
    INSIGHT = "insight"    # 洞察


@dataclass
class CouncilMessage:
    """议事厅消息"""
    id: str
    agent_id: str
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    score: float = 0.0  # 贡献值 (0-10)
    epoch: int = 0


@dataclass
class CouncilSession:
    """议事厅会话 (一个 Epoch)"""
    epoch: int
    messages: List[CouncilMessage] = field(default_factory=list)
    is_open: bool = False
    winner_id: Optional[str] = None
    
    def get_messages_for_agent(self, agent_id: str) -> List[CouncilMessage]:
        """获取其他 Agent 的消息"""
        return [m for m in self.messages if m.agent_id != agent_id]


class Council:
    """议事厅管理器"""
    
    def __init__(self):
        self.sessions: Dict[int, CouncilSession] = {}
        self.current_epoch = 0
        self.contribution_scores: Dict[str, float] = {}  # agent_id -> total score
        self.message_count = 0
    
    def start_session(self, epoch: int, winner_id: str) -> CouncilSession:
        """开启新的议事厅会话"""
        session = CouncilSession(epoch=epoch, is_open=True, winner_id=winner_id)
        self.sessions[epoch] = session
        self.current_epoch = epoch
        print(f"\n🏛️ Council Session #{epoch} opened. Winner: {winner_id}")
        return session
    
    def close_session(self, epoch: int):
        """关闭议事厅会话"""
        if epoch in self.sessions:
            self.sessions[epoch].is_open = False
            print(f"🏛️ Council Session #{epoch} closed.")
    
    async def submit_message(
        self, 
        epoch: int, 
        agent_id: str, 
        role: MessageRole, 
        content: str
    ) -> Optional[CouncilMessage]:
        """提交消息到议事厅"""
        # Auto-create session if missing (e.g. after restart or new epoch)
        session = self.sessions.get(epoch)
        if not session:
            session = CouncilSession(epoch=epoch, is_open=True, winner_id="Unknown")
            self.sessions[epoch] = session
            print(f"🏛️ Council Session #{epoch} auto-created (recovered).")
        
        # We allow messages even if session is technically "closed" (for chat/insights)
        
        self.message_count += 1
        message = CouncilMessage(
            id=f"MSG-{self.message_count:06d}",
            agent_id=agent_id,
            role=role,
            content=content,
            epoch=epoch
        )
        
        # 评分 (用 LLM)
        message.score = await self._score_message(message, session)
        
        # 累加贡献值
        if agent_id not in self.contribution_scores:
            self.contribution_scores[agent_id] = 0
        self.contribution_scores[agent_id] += message.score
        
        session.messages.append(message)
        
        role_emoji = {"winner": "🏆", "loser": "📝", "question": "❓", "insight": "💡"}
        print(f"{role_emoji.get(role.value, '💬')} [{agent_id}] ({message.score:.1f}pts): {content[:100]}...")
        
        return message
    
    async def _score_message(self, message: CouncilMessage, session: CouncilSession) -> float:
        """用 LLM 评分消息质量 (如果 LLM 可用)，否则用规则评分"""
        from config import LLM_ENABLED

        # 如果 LLM 未启用，使用规则评分
        if not LLM_ENABLED:
            score = score_council_message_rule_based(message.content)
            print(f"📊 Rule-based score: {score:.1f}/10")
            return score

        prompt = f"""你是一个交易策略议事厅的评委。请给以下发言打分 (0-10):

发言者: {message.agent_id}
角色: {message.role.value}
内容: {message.content}

评分标准:
- 0-2: 垃圾话/复读机/无意义
- 3-5: 一般性描述，没有深度
- 6-8: 有具体策略/数据支撑
- 9-10: 深刻洞察/创新思路

只回复一个数字 (0-10):"""

        try:
            result = await call_llm(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.1,
                timeout=10.0,
                max_retries=1,
            )
            if result:
                score_text = result.strip()
                return min(10, max(0, float(score_text)))
        except Exception as e:
            print(f"Scoring error (LLM unavailable): {e}")

        # 默认使用规则评分
        score = score_council_message_rule_based(message.content)
        print(f"📊 Fallback rule-based score: {score:.1f}/10")
        return score
    
    def get_winner_wisdom(self, epoch: int) -> str:
        """获取赢家的分享内容"""
        session = self.sessions.get(epoch)
        if not session:
            return ""
        
        winner_messages = [
            m for m in session.messages 
            if m.agent_id == session.winner_id and m.role == MessageRole.WINNER
        ]
        return "\n".join(m.content for m in winner_messages)
    
    def get_contribution_leaderboard(self) -> List[tuple]:
        """贡献值排行榜"""
        rankings = list(self.contribution_scores.items())
        rankings.sort(key=lambda x: x[1], reverse=True)
        return rankings

    def serialize_sessions(self) -> dict:
        """Serialize all sessions for Redis persistence"""
        result = {}
        for epoch, session in self.sessions.items():
            result[str(epoch)] = {
                "epoch": session.epoch,
                "is_open": session.is_open,
                "winner_id": session.winner_id,
                "messages": [
                    {
                        "id": m.id,
                        "agent_id": m.agent_id,
                        "role": m.role.value,
                        "content": m.content,
                        "score": m.score,
                        "epoch": m.epoch,
                        "timestamp": m.timestamp.isoformat(),
                    }
                    for m in session.messages
                ]
            }
        return result

    def restore_sessions(self, data: dict):
        """Restore sessions from Redis data"""
        for epoch_str, session_data in data.items():
            epoch = int(epoch_str)
            session = CouncilSession(
                epoch=epoch,
                is_open=session_data.get("is_open", False),
                winner_id=session_data.get("winner_id"),
            )
            for m_data in session_data.get("messages", []):
                msg = CouncilMessage(
                    id=m_data["id"],
                    agent_id=m_data["agent_id"],
                    role=MessageRole(m_data["role"]),
                    content=m_data["content"],
                    score=m_data.get("score", 0),
                    epoch=m_data.get("epoch", epoch),
                    timestamp=datetime.fromisoformat(m_data["timestamp"]) if m_data.get("timestamp") else datetime.now(),
                )
                session.messages.append(msg)
                # Restore contribution scores
                if msg.agent_id not in self.contribution_scores:
                    self.contribution_scores[msg.agent_id] = 0
                self.contribution_scores[msg.agent_id] += msg.score
            self.sessions[epoch] = session
            self.message_count += len(session.messages)
        if data:
            self.current_epoch = max(int(k) for k in data.keys())


# 测试
if __name__ == "__main__":
    council = Council()
    
    async def test():
        # 开启会话
        session = council.start_session(epoch=1, winner_id="Agent_001")
        
        # 赢家分享
        await council.submit_message(
            epoch=1,
            agent_id="Agent_001",
            role=MessageRole.WINNER,
            content="这轮我做空了 $MOLT，因为我发现链上大户在持续出货，24小时内有3个大钱包各卖出了超过10万美元。"
        )
        
        # 输家提问
        await council.submit_message(
            epoch=1,
            agent_id="Agent_002",
            role=MessageRole.QUESTION,
            content="你是怎么监控大户动向的？用什么数据源？"
        )
        
        # 输家反思
        await council.submit_message(
            epoch=1,
            agent_id="Agent_003",
            role=MessageRole.LOSER,
            content="我的止损太慢了，下次需要加入大户监控逻辑。"
        )
        
        council.close_session(epoch=1)
        
        print("\n📊 Contribution Leaderboard:")
        for agent_id, score in council.get_contribution_leaderboard():
            print(f"  {agent_id}: {score:.1f} pts")
    
    asyncio.run(test())
