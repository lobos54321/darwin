"""
数据持久化管理器
负责保存和加载 Arena 的状态 (排行榜、Epoch、议事厅记录)
"""

import json
import os
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
STATE_FILE = os.path.join(DATA_DIR, "arena_state.json")

class StateManager:
    def __init__(self, engine, council, ascension_tracker):
        self.engine = engine
        self.council = council
        self.ascension_tracker = ascension_tracker
        
        # 确保数据目录存在
        os.makedirs(DATA_DIR, exist_ok=True)
        
    def save_state(self, current_epoch: int):
        """保存当前状态到磁盘"""
        try:
            # 序列化 Council Sessions
            sessions_data = {}
            for epoch, session in self.council.sessions.items():
                sessions_data[str(epoch)] = {
                    "epoch": session.epoch,
                    "is_open": session.is_open,
                    "winner_id": session.winner_id,
                    "messages": [
                        {
                            "id": m.id,
                            "agent_id": m.agent_id,
                            "role": m.role.value,
                            "content": m.content,
                            "timestamp": m.timestamp.isoformat(),
                            "score": m.score
                        } for m in session.messages
                    ]
                }

            # 序列化 Ascension Tracker
            ascension_data = {
                "l1_consecutive_wins": self.ascension_tracker.l1_consecutive_wins,
                "l1_total_returns": self.ascension_tracker.l1_total_returns,
                "l2_qualified": list(self.ascension_tracker.l2_qualified),
                "l2_consecutive_wins": self.ascension_tracker.l2_consecutive_wins,
                "l2_total_returns": self.ascension_tracker.l2_total_returns,
                "ascended": list(self.ascension_tracker.ascended)
            }

            # Serialize agents accounts properly
            agents_serialized = {}
            for aid, acc in self.engine.accounts.items():
                agents_serialized[aid] = {
                    "balance": acc.balance,
                    "positions": {
                        sym: {
                            "amount": pos.amount,
                            "avg_price": pos.avg_price
                        } for sym, pos in acc.positions.items()
                    }
                }

            state = {
                "timestamp": datetime.now().isoformat(),
                "current_epoch": current_epoch,
                "agents": agents_serialized,
                "council_sessions": sessions_data,
                "council_scores": self.council.contribution_scores,
                "ascension": ascension_data
            }
            
            # 写入临时文件再重命名，防止写入中断导致文件损坏
            temp_file = STATE_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(state, f, indent=2)
            
            os.replace(temp_file, STATE_FILE)
            logger.info(f"💾 State saved (Epoch {current_epoch})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            return False

    def load_state(self) -> Dict[str, Any]:
        """从磁盘加载状态"""
        if not os.path.exists(STATE_FILE):
            logger.info("No saved state found, starting fresh.")
            return None
            
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            
            # 恢复 Matching Engine 状态
            from matching import AgentAccount, Position
            agents_data = state.get("agents", {})
            self.engine.accounts = {}
            for aid, adata in agents_data.items():
                acc = AgentAccount(agent_id=aid)
                acc.balance = adata.get("balance", 1000.0)
                # positions
                for sym, pdata in adata.get("positions", {}).items():
                    acc.positions[sym] = Position(
                        symbol=sym,
                        amount=pdata.get("amount", 0.0),
                        avg_price=pdata.get("avg_price", 0.0)
                    )
                self.engine.accounts[aid] = acc
            self.engine.agents = self.engine.accounts
            
            # 恢复 Council 状态
            from council import CouncilSession, CouncilMessage, MessageRole
            
            sessions_data = state.get("council_sessions", {})
            self.council.sessions = {}
            
            for epoch_str, s_data in sessions_data.items():
                epoch = int(epoch_str)
                messages = []
                for m_data in s_data.get("messages", []):
                    try:
                        messages.append(CouncilMessage(
                            id=m_data["id"],
                            agent_id=m_data["agent_id"],
                            role=MessageRole(m_data["role"]),
                            content=m_data["content"],
                            timestamp=datetime.fromisoformat(m_data["timestamp"]),
                            score=m_data["score"],
                            epoch=epoch
                        ))
                    except Exception as e:
                        logger.warning(f"Skipping malformed message: {e}")
                
                self.council.sessions[epoch] = CouncilSession(
                    epoch=epoch,
                    is_open=s_data.get("is_open", False),
                    winner_id=s_data.get("winner_id"),
                    messages=messages
                )
            
            self.council.contribution_scores = state.get("council_scores", {})
            
            # 恢复 Ascension Tracker
            ascension_data = state.get("ascension", {})
            
            # 兼容旧数据: 如果是旧版存档，迁移到 L1
            if "consecutive_wins" in ascension_data:
                logger.info("⚠️ Migrating legacy Ascension state to L1...")
                self.ascension_tracker.l1_consecutive_wins = ascension_data.get("consecutive_wins", {})
                self.ascension_tracker.l1_total_returns = ascension_data.get("total_returns", {})
            else:
                # 正常加载新版数据
                self.ascension_tracker.l1_consecutive_wins = ascension_data.get("l1_consecutive_wins", {})
                self.ascension_tracker.l1_total_returns = ascension_data.get("l1_total_returns", {})
                self.ascension_tracker.l2_qualified = set(ascension_data.get("l2_qualified", []))
                self.ascension_tracker.l2_consecutive_wins = ascension_data.get("l2_consecutive_wins", {})
                self.ascension_tracker.l2_total_returns = ascension_data.get("l2_total_returns", {})
                
            self.ascension_tracker.ascended = set(ascension_data.get("ascended", []))
            
            logger.info(f"📂 State loaded: Epoch {state.get('current_epoch', 0)}")
            return state
            
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return None

    async def auto_save_loop(self, get_epoch_func):
        """定期自动保存任务"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟保存一次
                current_epoch = get_epoch_func()
                self.save_state(current_epoch)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Auto-save error: {e}")
