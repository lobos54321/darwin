"""
Tournament / Season System
锦标赛/赛季系统 - 支持交易所赞助大赛
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

# 赛季配置目录
TOURNAMENT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "tournaments")
os.makedirs(TOURNAMENT_DIR, exist_ok=True)

@dataclass
class Tournament:
    """锦标赛/赛季"""
    id: str
    name: str
    sponsor: str
    sponsor_logo: str
    sponsor_link: str  # 带邀请码的注册链接
    
    start_date: str  # ISO format
    end_date: str
    
    prize_pool_usd: float
    prize_distribution: Dict[str, float]  # "1st": 2000, "2nd": 1000, etc
    
    tokens: List[str]  # 交易标的
    
    # 参赛要求
    require_exchange_registration: bool = True
    min_epochs: int = 50
    
    # 状态
    status: str = "upcoming"  # upcoming, active, ended
    
    # 参赛者
    participants: Dict[str, dict] = None  # agent_id -> {wallet, registered_at, exchange_uid}
    
    def __post_init__(self):
        if self.participants is None:
            self.participants = {}
    
    def is_active(self) -> bool:
        now = datetime.now()
        start = datetime.fromisoformat(self.start_date)
        end = datetime.fromisoformat(self.end_date)
        return start <= now <= end
    
    def register_participant(self, agent_id: str, wallet: str, exchange_uid: str = None):
        """报名参赛"""
        if agent_id in self.participants:
            return {"status": "already_registered"}
        
        self.participants[agent_id] = {
            "wallet": wallet,
            "registered_at": datetime.now().isoformat(),
            "exchange_uid": exchange_uid,
            "epochs_played": 0,
            "total_pnl": 0.0
        }
        return {"status": "registered", "agent_id": agent_id}
    
    def update_stats(self, agent_id: str, pnl: float):
        """更新参赛者统计"""
        if agent_id in self.participants:
            self.participants[agent_id]["epochs_played"] += 1
            self.participants[agent_id]["total_pnl"] += pnl
    
    def get_leaderboard(self) -> List[dict]:
        """获取赛季排行榜"""
        eligible = [
            {"agent_id": aid, **data}
            for aid, data in self.participants.items()
            if data["epochs_played"] >= self.min_epochs
        ]
        
        # 按总PnL排序
        eligible.sort(key=lambda x: x["total_pnl"], reverse=True)
        
        for i, entry in enumerate(eligible):
            entry["rank"] = i + 1
        
        return eligible
    
    def calculate_prizes(self) -> List[dict]:
        """计算奖金分配"""
        leaderboard = self.get_leaderboard()
        prizes = []
        
        for entry in leaderboard:
            rank = entry["rank"]
            prize = 0
            
            if rank == 1:
                prize = self.prize_distribution.get("1st", 0)
            elif rank == 2:
                prize = self.prize_distribution.get("2nd", 0)
            elif rank == 3:
                prize = self.prize_distribution.get("3rd", 0)
            elif 4 <= rank <= 10:
                prize = self.prize_distribution.get("4-10th", 0)
            elif 11 <= rank <= 50:
                prize = self.prize_distribution.get("11-50th", 0)
            
            if prize > 0:
                prizes.append({
                    "rank": rank,
                    "agent_id": entry["agent_id"],
                    "wallet": entry["wallet"],
                    "prize_usd": prize,
                    "total_pnl": entry["total_pnl"]
                })
        
        return prizes
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def save(self):
        """保存到文件"""
        path = os.path.join(TOURNAMENT_DIR, f"{self.id}.json")
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, tournament_id: str) -> Optional["Tournament"]:
        """从文件加载"""
        path = os.path.join(TOURNAMENT_DIR, f"{tournament_id}.json")
        if not os.path.exists(path):
            return None
        
        with open(path, "r") as f:
            data = json.load(f)
        
        return cls(**data)


class TournamentManager:
    """锦标赛管理器"""
    
    def __init__(self):
        self.tournaments: Dict[str, Tournament] = {}
        self.active_tournament: Optional[Tournament] = None
        self._load_all()
    
    def _load_all(self):
        """加载所有锦标赛"""
        if not os.path.exists(TOURNAMENT_DIR):
            return
        
        for fname in os.listdir(TOURNAMENT_DIR):
            if fname.endswith(".json"):
                tid = fname.replace(".json", "")
                t = Tournament.load(tid)
                if t:
                    self.tournaments[tid] = t
                    if t.is_active():
                        self.active_tournament = t
    
    def create_tournament(self, **kwargs) -> Tournament:
        """创建新锦标赛"""
        t = Tournament(**kwargs)
        self.tournaments[t.id] = t
        t.save()
        return t
    
    def get_active(self) -> Optional[Tournament]:
        """获取当前活跃的锦标赛"""
        for t in self.tournaments.values():
            if t.is_active():
                self.active_tournament = t
                return t
        return None
    
    def register_for_active(self, agent_id: str, wallet: str, exchange_uid: str = None) -> dict:
        """报名当前活跃锦标赛"""
        active = self.get_active()
        if not active:
            return {"status": "error", "message": "No active tournament"}
        
        result = active.register_participant(agent_id, wallet, exchange_uid)
        active.save()
        return result
    
    def on_epoch_end(self, rankings: list):
        """Epoch结束时更新锦标赛统计"""
        active = self.get_active()
        if not active:
            return
        
        for r in rankings:
            agent_id = r[0]
            pnl = r[1]
            if agent_id in active.participants:
                active.update_stats(agent_id, pnl)
        
        active.save()


# 创建默认示例锦标赛
def create_sample_tournament():
    """创建示例锦标赛（用于测试）"""
    sample = Tournament(
        id="mexc_cup_s1",
        name="MEXC Cup Season 1",
        sponsor="MEXC Exchange",
        sponsor_logo="https://www.mexc.com/images/logo.png",
        sponsor_link="https://www.mexc.com/register?inviteCode=darwin",
        start_date="2026-02-10T00:00:00",
        end_date="2026-02-24T23:59:59",
        prize_pool_usd=5000,
        prize_distribution={
            "1st": 2000,
            "2nd": 1000,
            "3rd": 500,
            "4-10th": 200,
            "11-50th": 20
        },
        tokens=["CLANKER", "MOLT", "LOB", "WETH"]  # Example only - actual tournaments support ANY token
    )
    sample.save()
    return sample
