"""
Hive Mind (蜂巢大脑)
实时分析全网交易数据，提取 Alpha 因子，并广播给所有 Agent
"""

import logging
from typing import List, Dict, Tuple
from collections import defaultdict
from matching import MatchingEngine

logger = logging.getLogger(__name__)

class HiveMind:
    def __init__(self, engine: MatchingEngine):
        self.engine = engine
        self.tag_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0.0})

    def analyze_alpha(self) -> Dict[str, dict]:
        """
        分析最近的交易历史，计算每个标签(Tag)的胜率和盈亏
        """
        # 获取最近 50 笔交易 (或更多)
        recent_trades = list(self.engine.trade_history)
        
        # 清空旧统计 (也可以做移动平均，这里简化为每轮重算)
        self.tag_stats.clear()
        
        # 简单的归因逻辑：
        # 这里的 trade_history 目前只记录了开仓(BUY)时的 tag
        # 我们需要知道这笔开仓后续是赚了还是亏了
        # 简化版：我们查看该 Agent 当前的总 PnL。
        # 如果 Agent 是盈利的，那么它用过的 Tag 都是好 Tag。
        
        for trade in recent_trades:
            agent_id = trade.get("agent")
            tags = trade.get("reason", [])
            
            if not agent_id or not tags:
                continue
                
            # 获取该 Agent 当前的盈亏状况
            # 这是一个近似值，更精确的做法是追踪每一笔平仓的 PnL
            current_pnl = self.engine.calculate_pnl(agent_id)
            
            for tag in tags:
                if current_pnl > 0:
                    self.tag_stats[tag]["wins"] += 1
                    self.tag_stats[tag]["total_pnl"] += current_pnl
                elif current_pnl < 0:
                    self.tag_stats[tag]["losses"] += 1
                    self.tag_stats[tag]["total_pnl"] += current_pnl

        # 总结 Alpha
        alpha_report = {}
        for tag, stats in self.tag_stats.items():
            total_trades = stats["wins"] + stats["losses"]
            if total_trades > 0:
                win_rate = (stats["wins"] / total_trades) * 100
                alpha_report[tag] = {
                    "win_rate": round(win_rate, 1),
                    "impact": "POSITIVE" if stats["total_pnl"] > 0 else "NEGATIVE",
                    "score": round(stats["total_pnl"], 2)
                }
        
        return alpha_report

    def generate_patch(self) -> dict:
        """
        生成全局策略补丁 (Patch)
        """
        report = self.analyze_alpha()
        
        # 筛选出显著的因子
        boost_tags = []
        penalize_tags = []
        
        for tag, data in report.items():
            if data["impact"] == "POSITIVE" and data["win_rate"] > 60:
                boost_tags.append(tag)
            elif data["impact"] == "NEGATIVE" and data["win_rate"] < 40:
                penalize_tags.append(tag)
                
        if not boost_tags and not penalize_tags:
            return None
            
        patch = {
            "type": "hive_patch",
            "epoch": 0, # 这里应该填实际 epoch，简化处理
            "message": "Hive Mind Strategy Update",
            "parameters": {
                "boost": boost_tags,
                "penalize": penalize_tags
            },
            "stats": report
        }
        
        logger.info(f"🧠 Hive Mind generated patch: Boost={boost_tags}, Penalize={penalize_tags}")
        return patch
