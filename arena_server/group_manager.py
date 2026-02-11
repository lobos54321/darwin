"""
GroupManager - 分组竞技管理器

核心设计：
1. 动态分组：根据总人数自动调整每组大小 (10→20→50→100)
2. 代币池轮转：每个新组分配不同的代币池（多链: Base, ETH, Solana...）
3. 独立进化：每组有自己的 MatchingEngine + HiveMind
4. 冠军赛：各组冠军可晋级跨组总决赛

架构:
  GroupManager
    ├── Group 0 (Base memes: CLANKER/MOLT/LOB/WETH)
    │     ├── engine (MatchingEngine)
    │     ├── hive_mind (HiveMind)
    │     ├── feeder (DexScreenerFeeder)
    │     └── members: {Agent_001, Agent_002, ...}
    ├── Group 1 (Base blue chips: DEGEN/BRETT/TOSHI/HIGHER)
    │     ├── engine / hive_mind / feeder
    │     └── members: {Agent_011, Agent_012, ...}
    ├── Group 2 (ETH memes: PEPE/SHIB/FLOKI/TURBO)
    └── Group 3 (Solana memes: WIF/BONK/POPCAT/MEW)
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set
from collections import deque

from matching import MatchingEngine, OrderSide, Position
from hive_mind import HiveMind
from feeder import DexScreenerFeeder
from config import TOKEN_POOLS, GROUP_SIZE_THRESHOLDS, GROUP_DEFAULT_SIZE, INITIAL_BALANCE

logger = logging.getLogger(__name__)


class Group:
    """一个竞技小组 — 独立的交易+进化单元"""

    def __init__(self, group_id: int, token_pool: Dict[str, str]):
        self.group_id = group_id
        self.token_pool = token_pool  # {symbol: address}
        self.members: Set[str] = set()
        self.engine = MatchingEngine()
        self.hive_mind = HiveMind(self.engine)
        self.feeder = DexScreenerFeeder(tokens=token_pool)
        self._feeder_task: Optional[asyncio.Task] = None

        # Wire feeder → engine price updates
        self.feeder.subscribe(lambda prices: self.engine.update_prices(prices))

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def token_symbols(self) -> List[str]:
        return list(self.token_pool.keys())

    def add_member(self, agent_id: str):
        self.members.add(agent_id)
        self.engine.register_agent(agent_id)

    def remove_member(self, agent_id: str):
        self.members.discard(agent_id)

    async def start_feeder(self):
        """Start the group's price feeder"""
        if self._feeder_task is None or self._feeder_task.done():
            self._feeder_task = asyncio.create_task(self.feeder.start())
            logger.info(f"📡 Group {self.group_id} feeder started: {self.token_symbols}")

    def stop_feeder(self):
        if self._feeder_task and not self._feeder_task.done():
            self._feeder_task.cancel()


class GroupManager:
    """
    分组竞技管理器

    职责：
    1. Agent 分组分配（动态大小）
    2. 代币池轮转（多链）
    3. 每组独立的交易引擎和蜂巢大脑
    4. 统一的对外接口（兼容原 MatchingEngine API）
    """

    def __init__(self):
        self.groups: Dict[int, Group] = {}
        self.agent_to_group: Dict[str, int] = {}
        self._next_group_id = 0
        self._pool_index = 0

    # ========== Properties for backward compat ==========

    @property
    def total_agents(self) -> int:
        return sum(g.size for g in self.groups.values())

    @property
    def accounts(self) -> Dict:
        """Merged accounts from all groups (for StateManager compat)"""
        merged = {}
        for group in self.groups.values():
            merged.update(group.engine.accounts)
        return merged

    @property
    def agents(self):
        """Alias for accounts (MatchingEngine compat)"""
        return self.accounts

    @property
    def current_prices(self) -> Dict[str, float]:
        """Merged prices from all groups"""
        merged = {}
        for group in self.groups.values():
            merged.update(group.engine.current_prices)
        return merged

    @property
    def trade_history(self) -> deque:
        """Merged trade history from all groups"""
        merged = deque(maxlen=2000)
        for group in self.groups.values():
            merged.extend(group.engine.trade_history)
        return merged

    @property
    def order_count(self) -> int:
        return sum(g.engine.order_count for g in self.groups.values())

    # ========== Dynamic Sizing ==========

    def dynamic_group_size(self) -> int:
        """根据总Agent数动态计算每组大小"""
        total = self.total_agents
        for threshold in sorted(GROUP_SIZE_THRESHOLDS.keys()):
            if total < threshold:
                return GROUP_SIZE_THRESHOLDS[threshold]
        return GROUP_DEFAULT_SIZE

    # ========== Group Lifecycle ==========

    def _next_token_pool(self) -> Dict[str, str]:
        """轮转分配代币池"""
        pool = TOKEN_POOLS[self._pool_index % len(TOKEN_POOLS)]
        self._pool_index += 1
        return pool.copy()

    def _create_group(self) -> Group:
        """创建新组"""
        group_id = self._next_group_id
        self._next_group_id += 1
        token_pool = self._next_token_pool()
        group = Group(group_id=group_id, token_pool=token_pool)
        self.groups[group_id] = group
        logger.info(f"🆕 Created Group {group_id} | Tokens: {group.token_symbols}")
        return group

    async def assign_agent(self, agent_id: str) -> Group:
        """
        将Agent分配到组。已有组则返回现有组，否则找未满组或创建新组。
        同时确保该组的feeder已启动。
        """
        if agent_id in self.agent_to_group:
            return self.groups[self.agent_to_group[agent_id]]

        max_size = self.dynamic_group_size()

        # Find an available group
        for group in self.groups.values():
            if group.size < max_size:
                group.add_member(agent_id)
                self.agent_to_group[agent_id] = group.group_id
                logger.info(
                    f"👤 {agent_id} → Group {group.group_id} "
                    f"({group.size}/{max_size}) "
                    f"Tokens: {group.token_symbols}"
                )
                return group

        # All groups full → create new
        group = self._create_group()
        group.add_member(agent_id)
        self.agent_to_group[agent_id] = group.group_id
        await group.start_feeder()
        logger.info(
            f"👤 {agent_id} → Group {group.group_id} (new) "
            f"Tokens: {group.token_symbols}"
        )
        return group

    def get_group(self, agent_id: str) -> Optional[Group]:
        """获取Agent所在的组"""
        group_id = self.agent_to_group.get(agent_id)
        return self.groups.get(group_id) if group_id is not None else None

    def get_group_by_id(self, group_id: int) -> Optional[Group]:
        return self.groups.get(group_id)

    # ========== MatchingEngine 代理接口 ==========

    def register_agent(self, agent_id: str):
        """Sync version of assign_agent for backward compat (no feeder start)"""
        if agent_id in self.agent_to_group:
            return self.groups[self.agent_to_group[agent_id]].engine.accounts.get(agent_id)

        max_size = self.dynamic_group_size()
        for group in self.groups.values():
            if group.size < max_size:
                group.add_member(agent_id)
                self.agent_to_group[agent_id] = group.group_id
                return group.engine.accounts.get(agent_id)

        group = self._create_group()
        group.add_member(agent_id)
        self.agent_to_group[agent_id] = group.group_id
        return group.engine.accounts.get(agent_id)

    async def execute_order(self, agent_id: str, symbol: str, side: OrderSide,
                      amount_usd: float, reason: list = None) -> tuple:
        """Route order to the agent's group engine"""
        group = self.get_group(agent_id)
        if not group:
            return (False, "Agent not in any group", 0.0)
        return await group.engine.execute_order(agent_id, symbol, side, amount_usd, reason)

    def get_balance(self, agent_id: str) -> float:
        group = self.get_group(agent_id)
        return group.engine.get_balance(agent_id) if group else 0.0

    def get_positions(self, agent_id: str) -> dict:
        group = self.get_group(agent_id)
        return group.engine.get_positions(agent_id) if group else {}

    def calculate_pnl(self, agent_id: str) -> float:
        group = self.get_group(agent_id)
        return group.engine.calculate_pnl(agent_id) if group else 0.0

    def get_account(self, agent_id: str):
        group = self.get_group(agent_id)
        return group.engine.get_account(agent_id) if group else None

    def update_prices(self, prices: Dict[str, dict]):
        """Update prices — routes to all groups (for futures feeder compat)"""
        for group in self.groups.values():
            group.engine.update_prices(prices)

    # ========== Leaderboard ==========

    def get_leaderboard(self, group_id: int = None) -> list:
        """
        获取排行榜
        group_id=None → 全局合并排行（附带 group_id 信息）
        group_id=N → 仅该组的排行
        """
        if group_id is not None:
            group = self.groups.get(group_id)
            return group.engine.get_leaderboard() if group else []

        # Global merged leaderboard
        all_rankings = []
        for group in self.groups.values():
            for agent_id, pnl_pct, total_val in group.engine.get_leaderboard():
                all_rankings.append((agent_id, pnl_pct, total_val))
        all_rankings.sort(key=lambda x: x[1], reverse=True)
        return all_rankings

    def print_leaderboard(self):
        """Print per-group leaderboards"""
        for group in self.groups.values():
            print(f"\n🏆 Group {group.group_id} ({group.token_symbols})")
            group.engine.print_leaderboard()

    # ========== Group-Aware Prices ==========

    def get_agent_prices(self, agent_id: str) -> dict:
        """获取Agent所在组的价格数据"""
        group = self.get_group(agent_id)
        return group.feeder.prices if group else {}

    # ========== Feeder Management ==========

    async def start_all_feeders(self):
        """Start all group feeders"""
        for group in self.groups.values():
            await group.start_feeder()

    def stop_all_feeders(self):
        """Stop all group feeders"""
        for group in self.groups.values():
            group.stop_feeder()

    # ========== Hive Mind ==========

    async def hive_mind_tick(self, epoch: int, broadcast_fn) -> int:
        """
        Run hive mind analysis for all groups.
        broadcast_fn(group_id, message) is called for each group with a patch.
        Returns number of patches generated.
        """
        patches = 0
        for group in self.groups.values():
            try:
                patch = group.hive_mind.generate_patch()
                if patch:
                    patch["epoch"] = epoch
                    patch["group_id"] = group.group_id
                    await broadcast_fn(group.group_id, patch)
                    patches += 1
            except Exception as e:
                logger.error(f"Hive Mind error (Group {group.group_id}): {e}")
        return patches

    # ========== Agent Removal ==========

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent completely from its group"""
        group_id = self.agent_to_group.pop(agent_id, None)
        if group_id is None:
            return False
        group = self.groups.get(group_id)
        if group:
            group.members.discard(agent_id)
            group.engine.accounts.pop(agent_id, None)
        return True

    # ========== Stats ==========

    def get_stats(self) -> dict:
        """Get comprehensive group stats"""
        return {
            "total_agents": self.total_agents,
            "total_groups": len(self.groups),
            "current_group_size": self.dynamic_group_size(),
            "groups": {
                gid: {
                    "members": group.size,
                    "member_list": list(group.members),
                    "tokens": group.token_symbols,
                    "trades": group.engine.order_count,
                }
                for gid, group in self.groups.items()
            }
        }

    # ========== State Persistence Helpers ==========

    def get_all_accounts_data(self) -> dict:
        """Serialize all agent accounts across groups for state saving"""
        result = {}
        for group in self.groups.values():
            for aid, acc in group.engine.accounts.items():
                result[aid] = {
                    "balance": acc.balance,
                    "positions": {
                        sym: {"amount": pos.amount, "avg_price": pos.avg_price}
                        for sym, pos in acc.positions.items()
                    },
                    "pnl": acc.get_pnl(group.engine.current_prices),
                    "group_id": group.group_id,
                }
        return result

    def restore_agent(self, agent_id: str, balance: float,
                      positions: dict, group_id: int = None):
        """Restore an agent's account from saved state"""
        # Assign to specific group or next available
        if group_id is not None and group_id in self.groups:
            group = self.groups[group_id]
            if agent_id not in group.members:
                group.add_member(agent_id)
                self.agent_to_group[agent_id] = group_id
        else:
            group = None
            for g in self.groups.values():
                if g.size < self.dynamic_group_size():
                    g.add_member(agent_id)
                    self.agent_to_group[agent_id] = g.group_id
                    group = g
                    break
            if not group:
                group = self._create_group()
                group.add_member(agent_id)
                self.agent_to_group[agent_id] = group.group_id

        # Restore account state
        account = group.engine.accounts.get(agent_id)
        if account:
            account.balance = balance
            for sym, pdata in positions.items():
                if isinstance(pdata, dict):
                    account.positions[sym] = Position(
                        symbol=sym,
                        amount=pdata.get("amount", 0.0),
                        avg_price=pdata.get("avg_price", 0.0)
                    )
