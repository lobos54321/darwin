"""
Hive Mind (蜂巢大脑)
三步闭环：分布式试错 → 中央学习 → 广播进化

Step 1: Agent 下单带标签 (reason tags) — 由 Strategy 和 matching.py 完成
Step 2: 归因分析 (Attribution) — 本模块的 analyze_alpha()
Step 3: 全网热更新 (Hot Patch) — 本模块的 generate_patch()

归因逻辑：
- 追踪每笔 SELL 的 trade_pnl (已平仓盈亏)
- 回溯该 Agent 同 symbol 的 BUY 标签
- 将盈亏归因到 BUY 标签上
- 统计每个标签的胜率和平均 PnL
"""

import logging
from typing import List, Dict
from collections import defaultdict
from matching import MatchingEngine

logger = logging.getLogger(__name__)


class HiveMind:
    def __init__(self, engine: MatchingEngine):
        self.engine = engine
        # Per-tag attribution: {tag: {"wins": N, "losses": N, "total_pnl": X, "trades": N}}
        self.tag_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0.0, "trades": 0})
        # Per-agent tag usage: {agent_id: {tag: count}}
        self.agent_tags = defaultdict(lambda: defaultdict(int))
        # Enhanced granular stats
        self.tag_by_token = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0.0, "trades": 0}))
        self.tag_combos = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0.0, "trades": 0})
        self.tag_history = defaultdict(list)  # Track recent performance for trend analysis

    def analyze_alpha(self) -> Dict[str, dict]:
        """
        精确归因：基于每笔已平仓交易的实际 PnL。
        增强版：添加 by_token, by_combo, trend 等细粒度分析

        逻辑:
        1. 找到所有 SELL 记录 (有 trade_pnl)
        2. 回溯同 Agent + 同 Symbol 的 BUY 记录的 reason tags
        3. 将 SELL 的 PnL 归因到这些 BUY tags 上
        4. SELL 自身的 tags (TAKE_PROFIT, STOP_LOSS 等) 也记录
        5. 细分统计：by_token, by_combo, trend
        """
        trades = list(self.engine.trade_history)
        self.tag_stats.clear()
        self.agent_tags.clear()
        self.tag_by_token.clear()
        self.tag_combos.clear()

        # Index BUY trades by (agent, symbol) for fast lookup
        buy_index = defaultdict(list)  # {(agent, symbol): [trade, ...]}
        for t in trades:
            if t.get("side") == "BUY":
                key = (t.get("agent_id", t.get("agent")), t["symbol"])
                buy_index[key].append(t)

        # Process all SELL trades with known PnL
        for t in trades:
            if t.get("side") != "SELL":
                continue
            trade_pnl = t.get("trade_pnl")
            if trade_pnl is None:
                continue

            agent_id = t.get("agent_id", t.get("agent"))
            symbol = t["symbol"]
            is_win = trade_pnl > 0
            timestamp = t.get("timestamp", 0)

            # 1. Attribute to the BUY entry tags (WHY did we enter?)
            buy_key = (agent_id, symbol)
            entry_tags = []
            if buy_key in buy_index and buy_index[buy_key]:
                # Use the most recent BUY for this (agent, symbol)
                latest_buy = buy_index[buy_key][-1]
                entry_tags = latest_buy.get("reason", [])

            # 2. Also record the SELL tags (WHY did we exit?)
            exit_tags = t.get("reason", [])

            # 3. Attribute PnL to entry tags (most important)
            for tag in entry_tags:
                # Overall stats
                self.tag_stats[tag]["trades"] += 1
                self.tag_stats[tag]["total_pnl"] += trade_pnl
                if is_win:
                    self.tag_stats[tag]["wins"] += 1
                else:
                    self.tag_stats[tag]["losses"] += 1

                # Track per-agent usage
                self.agent_tags[agent_id][tag] += 1

                # By-token breakdown
                self.tag_by_token[tag][symbol]["trades"] += 1
                self.tag_by_token[tag][symbol]["total_pnl"] += trade_pnl
                if is_win:
                    self.tag_by_token[tag][symbol]["wins"] += 1
                else:
                    self.tag_by_token[tag][symbol]["losses"] += 1

                # Track history for trend analysis (keep last 20 trades per tag)
                self.tag_history[tag].append({
                    "pnl": trade_pnl,
                    "timestamp": timestamp,
                    "is_win": is_win
                })
                if len(self.tag_history[tag]) > 20:
                    self.tag_history[tag].pop(0)

            # 4. Track tag combinations (if multiple entry tags)
            if len(entry_tags) >= 2:
                combo_key = "+".join(sorted(entry_tags))
                self.tag_combos[combo_key]["trades"] += 1
                self.tag_combos[combo_key]["total_pnl"] += trade_pnl
                if is_win:
                    self.tag_combos[combo_key]["wins"] += 1
                else:
                    self.tag_combos[combo_key]["losses"] += 1

            # 5. Also attribute to exit tags (secondary signal)
            for tag in exit_tags:
                if tag.startswith("PNL_"):
                    continue  # Skip PnL info tags
                self.tag_stats[tag]["trades"] += 1
                self.tag_stats[tag]["total_pnl"] += trade_pnl
                if is_win:
                    self.tag_stats[tag]["wins"] += 1
                else:
                    self.tag_stats[tag]["losses"] += 1
                
                # Also build by_token for exit tags (TAKE_PROFIT, STOP_LOSS, etc.)
                self.tag_by_token[tag][symbol]["trades"] += 1
                self.tag_by_token[tag][symbol]["total_pnl"] += trade_pnl
                if is_win:
                    self.tag_by_token[tag][symbol]["wins"] += 1
                else:
                    self.tag_by_token[tag][symbol]["losses"] += 1

        # Build enhanced alpha report
        alpha_report = {}
        for tag, stats in self.tag_stats.items():
            total = stats["wins"] + stats["losses"]
            if total < 2:  # Need minimum samples
                continue

            win_rate = (stats["wins"] / total) * 100
            avg_pnl = stats["total_pnl"] / total

            # Build by_token breakdown
            by_token = {}
            if tag in self.tag_by_token:
                for symbol, token_stats in self.tag_by_token[tag].items():
                    token_total = token_stats["wins"] + token_stats["losses"]
                    if token_total >= 1:
                        by_token[symbol] = {
                            "win_rate": round((token_stats["wins"] / token_total) * 100, 1),
                            "avg_pnl": round(token_stats["total_pnl"] / token_total, 2),
                            "trades": token_total
                        }

            # Calculate trend (recent 10 trades vs older 10 trades)
            trend = "stable"
            if tag in self.tag_history and len(self.tag_history[tag]) >= 10:
                history = self.tag_history[tag]
                recent_pnl = sum(h["pnl"] for h in history[-10:]) / 10
                older_pnl = sum(h["pnl"] for h in history[-20:-10]) / 10 if len(history) >= 20 else recent_pnl

                if recent_pnl > older_pnl * 1.2:
                    trend = "improving"
                elif recent_pnl < older_pnl * 0.8:
                    trend = "declining"

            alpha_report[tag] = {
                "win_rate": round(win_rate, 1),
                "avg_pnl": round(avg_pnl, 2),
                "trades": total,
                "impact": "POSITIVE" if avg_pnl > 0 else "NEGATIVE",
                "score": round(stats["total_pnl"], 2),
                "by_token": by_token,
                "recent_trend": trend
            }

        # Add best combos to report
        best_combos = []
        for combo_key, combo_stats in self.tag_combos.items():
            combo_total = combo_stats["wins"] + combo_stats["losses"]
            if combo_total >= 2:
                combo_win_rate = (combo_stats["wins"] / combo_total) * 100
                combo_avg_pnl = combo_stats["total_pnl"] / combo_total
                if combo_avg_pnl > 0:
                    best_combos.append({
                        "combo": combo_key.split("+"),
                        "win_rate": round(combo_win_rate, 1),
                        "avg_pnl": round(combo_avg_pnl, 2),
                        "trades": combo_total
                    })

        # Sort by avg_pnl and keep top 5
        best_combos.sort(key=lambda x: x["avg_pnl"], reverse=True)
        alpha_report["_meta"] = {
            "best_combos": best_combos[:5],
            "supported_tokens": "ANY",
            "supported_chains": ["base", "ethereum", "solana", "polygon", "arbitrum", "optimism", "avalanche", "bsc", "fantom", "cronos"],
            "note": "You can trade ANY token on DexScreener (50+ chains supported). The 'by_token' field only shows historical performance data for tokens that have been traded with complete buy-sell cycles. Don't limit yourself to these tokens - explore and discover new opportunities!"
        }

        return alpha_report

    def get_agent_profile(self, agent_id: str) -> Dict[str, int]:
        """获取单个 Agent 的标签使用画像"""
        return dict(self.agent_tags.get(agent_id, {}))

    def generate_patch(self) -> dict:
        """
        生成全局策略补丁 (Hot Patch).
        包含:
        - boost: 高胜率标签 (>55% 且样本 >= 3)
        - penalize: 低胜率标签 (<45% 且样本 >= 3)
        - alpha_factors: 完整因子报告 (供 Agent 自行解读)
        """
        report = self.analyze_alpha()

        # Risk management tags must NEVER be penalized.
        # STOP_LOSS always has negative PnL by design — that's its job.
        # TAKE_PROFIT always has positive PnL — penalizing it kills profit-taking.
        # Exit signals are protective mechanisms, not entry strategies.
        PROTECTED_TAGS = {
            "TAKE_PROFIT", "STOP_LOSS", "TRAILING_STOP",
            "DIVERGENCE_EXIT", "BEARISH_DIV", "IDLE_EXIT",
            "RANDOM_TEST", "EXPLORE",
            "ATR_TRAIL_STOP", "VOL_TARGET_HIT", "TIME_DECAY", "STAGNANT",
        }

        boost_tags = []
        penalize_tags = []

        for tag, data in report.items():
            if tag.startswith("_"):  # Skip meta keys like "_meta"
                continue
            if tag in PROTECTED_TAGS:
                continue  # Never boost or penalize risk management / exploration tags
            if data["impact"] == "POSITIVE" and data["win_rate"] > 55 and data["trades"] >= 3:
                boost_tags.append(tag)
            elif data["impact"] == "NEGATIVE" and data["win_rate"] < 45 and data["trades"] >= 3:
                penalize_tags.append(tag)

        if not boost_tags and not penalize_tags:
            return None

        patch = {
            "type": "hive_patch",
            "epoch": 0,
            "message": "Hive Mind Strategy Update",
            "parameters": {
                "boost": boost_tags,
                "penalize": penalize_tags
            },
            "alpha_factors": report,
            "stats": report  # Backward compatibility
        }

        logger.info(f"Hive Mind patch: Boost={boost_tags}, Penalize={penalize_tags}")
        return patch
