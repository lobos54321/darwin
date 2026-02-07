"""
Redis State Manager
使用Redis持久化Arena状态，解决服务器重启数据丢失问题
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Redis配置 - 从环境变量读取
REDIS_HOST = os.getenv("REDIS_HOST", "sfo1.clusters.zeabur.com")
REDIS_PORT = int(os.getenv("REDIS_PORT", "31441"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# Redis Keys
KEY_API_KEYS = "darwin:api_keys"  # Hash: api_key -> agent_id
KEY_AGENTS = "darwin:agents"  # Hash: agent_id -> account_json
KEY_EPOCH = "darwin:current_epoch"  # String: epoch number
KEY_TRADE_COUNT = "darwin:trade_count"  # String: trade count
KEY_TOTAL_VOLUME = "darwin:total_volume"  # String: total volume
KEY_LEADERBOARD = "darwin:leaderboard"  # Sorted Set: agent_id -> pnl
KEY_IP_LIMITS = "darwin:ip_limits"  # Hash: ip -> count
KEY_TRADE_HISTORY = "darwin:trade_history"  # String: JSON list of recent trades
KEY_COUNCIL_SESSIONS = "darwin:council_sessions"  # String: JSON dict of council sessions


class RedisStateManager:
    """Redis状态管理器（含断线重连）"""

    def __init__(self):
        self.redis = None
        self.enabled = False
        self._connect()

    def _connect(self):
        """连接Redis"""
        try:
            import redis
            self.redis = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                decode_responses=True,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
            self.redis.ping()
            self.enabled = True
            logger.info(f"✅ Redis connected: {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            logger.warning(f"⚠️ Redis not available: {e}. Using in-memory storage.")
            self.enabled = False

    def _ensure_connection(self):
        """检查连接，断线自动重连"""
        if not self.enabled:
            self._connect()
            return
        try:
            self.redis.ping()
        except Exception:
            logger.warning("⚠️ Redis connection lost, reconnecting...")
            self._connect()
    
    # === API Keys ===
    
    def save_api_key(self, api_key: str, agent_id: str):
        """保存API Key"""
        if not self.enabled:
            return
        try:
            self.redis.hset(KEY_API_KEYS, api_key, agent_id)
        except Exception as e:
            logger.error(f"Redis save_api_key error: {e}")
    
    def get_api_keys(self) -> Dict[str, str]:
        """获取所有API Keys"""
        if not self.enabled:
            return {}
        try:
            return self.redis.hgetall(KEY_API_KEYS) or {}
        except Exception as e:
            logger.error(f"Redis get_api_keys error: {e}")
            return {}
    
    def get_agent_by_key(self, api_key: str) -> Optional[str]:
        """根据API Key获取agent_id"""
        if not self.enabled:
            return None
        try:
            return self.redis.hget(KEY_API_KEYS, api_key)
        except:
            return None
    
    # === Agent Accounts ===
    
    def save_agent(self, agent_id: str, account_data: dict):
        """保存Agent账户数据"""
        if not self.enabled:
            return
        try:
            self.redis.hset(KEY_AGENTS, agent_id, json.dumps(account_data))
        except Exception as e:
            logger.error(f"Redis save_agent error: {e}")
    
    def get_agent(self, agent_id: str) -> Optional[dict]:
        """获取Agent账户数据"""
        if not self.enabled:
            return None
        try:
            data = self.redis.hget(KEY_AGENTS, agent_id)
            return json.loads(data) if data else None
        except:
            return None
    
    def get_all_agents(self) -> Dict[str, dict]:
        """获取所有Agent账户"""
        if not self.enabled:
            return {}
        try:
            result = {}
            all_data = self.redis.hgetall(KEY_AGENTS)
            for agent_id, data in all_data.items():
                result[agent_id] = json.loads(data)
            return result
        except Exception as e:
            logger.error(f"Redis get_all_agents error: {e}")
            return {}
    
    # === Epoch & Stats ===
    
    def save_epoch(self, epoch: int):
        """保存当前Epoch"""
        if not self.enabled:
            return
        try:
            self.redis.set(KEY_EPOCH, str(epoch))
        except:
            pass
    
    def get_epoch(self) -> int:
        """获取当前Epoch"""
        if not self.enabled:
            return 1
        try:
            val = self.redis.get(KEY_EPOCH)
            return int(val) if val else 1
        except:
            return 1
    
    def save_stats(self, trade_count: int, total_volume: float):
        """保存统计数据"""
        if not self.enabled:
            return
        try:
            self.redis.set(KEY_TRADE_COUNT, str(trade_count))
            self.redis.set(KEY_TOTAL_VOLUME, str(total_volume))
        except:
            pass
    
    def get_stats(self) -> tuple:
        """获取统计数据 (trade_count, total_volume)"""
        if not self.enabled:
            return (0, 0.0)
        try:
            tc = self.redis.get(KEY_TRADE_COUNT)
            tv = self.redis.get(KEY_TOTAL_VOLUME)
            return (int(tc) if tc else 0, float(tv) if tv else 0.0)
        except:
            return (0, 0.0)
    
    # === IP Rate Limiting ===
    
    def get_ip_agent_count(self, ip: str) -> int:
        """获取IP的Agent数量"""
        if not self.enabled:
            return 0
        try:
            val = self.redis.hget(KEY_IP_LIMITS, ip)
            return int(val) if val else 0
        except:
            return 0
    
    def increment_ip_agent_count(self, ip: str) -> int:
        """增加IP的Agent数量"""
        if not self.enabled:
            return 1
        try:
            return self.redis.hincrby(KEY_IP_LIMITS, ip, 1)
        except:
            return 1
    
    # === Leaderboard ===
    
    def update_leaderboard(self, agent_id: str, pnl: float):
        """更新排行榜"""
        if not self.enabled:
            return
        try:
            self.redis.zadd(KEY_LEADERBOARD, {agent_id: pnl})
        except:
            pass
    
    def get_leaderboard(self, limit: int = 100) -> list:
        """获取排行榜 (按PnL降序)"""
        if not self.enabled:
            return []
        try:
            # 返回 [(agent_id, pnl), ...]
            return self.redis.zrevrange(KEY_LEADERBOARD, 0, limit - 1, withscores=True)
        except:
            return []
    
    # === Bulk Operations ===

    def save_trade_history(self, trades: list):
        """Save recent trade history"""
        if not self.enabled:
            return
        try:
            # Keep last 200 trades
            self.redis.set(KEY_TRADE_HISTORY, json.dumps(trades[:200]))
        except Exception as e:
            logger.error(f"Redis save_trade_history error: {e}")

    def load_trade_history(self) -> list:
        """Load trade history"""
        if not self.enabled:
            return []
        try:
            data = self.redis.get(KEY_TRADE_HISTORY)
            return json.loads(data) if data else []
        except Exception as e:
            logger.error(f"Redis load_trade_history error: {e}")
            return []

    def save_council_sessions(self, sessions_data: dict):
        """Save council sessions"""
        if not self.enabled:
            return
        try:
            self.redis.set(KEY_COUNCIL_SESSIONS, json.dumps(sessions_data))
        except Exception as e:
            logger.error(f"Redis save_council_sessions error: {e}")

    def load_council_sessions(self) -> dict:
        """Load council sessions"""
        if not self.enabled:
            return {}
        try:
            data = self.redis.get(KEY_COUNCIL_SESSIONS)
            return json.loads(data) if data else {}
        except Exception as e:
            logger.error(f"Redis load_council_sessions error: {e}")
            return {}

    def save_full_state(self, epoch: int, trade_count: int, total_volume: float,
                        api_keys: dict, agents: dict,
                        trade_history: list = None, council_sessions: dict = None):
        """保存完整状态（用于定期备份）"""
        self._ensure_connection()
        if not self.enabled:
            return
        try:
            pipe = self.redis.pipeline()
            pipe.set(KEY_EPOCH, str(epoch))
            pipe.set(KEY_TRADE_COUNT, str(trade_count))
            pipe.set(KEY_TOTAL_VOLUME, str(total_volume))

            # API Keys
            if api_keys:
                pipe.delete(KEY_API_KEYS)
                pipe.hset(KEY_API_KEYS, mapping=api_keys)

            # Agents
            if agents:
                agents_json = {aid: json.dumps(data) for aid, data in agents.items()}
                pipe.delete(KEY_AGENTS)
                pipe.hset(KEY_AGENTS, mapping=agents_json)

            # Trade History
            if trade_history is not None:
                pipe.set(KEY_TRADE_HISTORY, json.dumps(trade_history[:200]))

            # Council Sessions
            if council_sessions is not None:
                pipe.set(KEY_COUNCIL_SESSIONS, json.dumps(council_sessions))

            pipe.execute()
            logger.info(f"💾 Redis state saved (Epoch {epoch}, {len(agents)} agents)")
        except Exception as e:
            logger.error(f"Redis save_full_state error: {e}")
    
    def load_full_state(self) -> Optional[dict]:
        """加载完整状态"""
        self._ensure_connection()
        if not self.enabled:
            return None
        try:
            epoch = self.get_epoch()
            tc, tv = self.get_stats()
            api_keys = self.get_api_keys()
            agents = self.get_all_agents()
            trade_history = self.load_trade_history()
            council_sessions = self.load_council_sessions()

            if epoch > 1 or api_keys or agents:
                logger.info(f"📂 Redis state loaded: Epoch {epoch}, {len(agents)} agents, {len(api_keys)} keys, {len(trade_history)} trades, {len(council_sessions)} council sessions")
                return {
                    "epoch": epoch,
                    "trade_count": tc,
                    "total_volume": tv,
                    "api_keys": api_keys,
                    "agents": agents,
                    "trade_history": trade_history,
                    "council_sessions": council_sessions,
                }
            return None
        except Exception as e:
            logger.error(f"Redis load_full_state error: {e}")
            return None


# 全局实例
redis_state = RedisStateManager()
