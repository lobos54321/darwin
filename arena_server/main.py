"""
Project Darwin - Arena Server
主入口: FastAPI + WebSocket
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request, Header, Body
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from pydantic import BaseModel
from contextlib import asynccontextmanager
import json
import os
import secrets
import traceback
import subprocess
import sys
from dotenv import load_dotenv

# Load environment variables from ../.env
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(env_path)

from config import EPOCH_DURATION_HOURS, ELIMINATION_THRESHOLD, ASCENSION_THRESHOLD, INITIAL_BALANCE
from feeder import DexScreenerFeeder
from feeder_futures import FuturesFeeder
from matching import MatchingEngine, OrderSide
from council import Council, MessageRole
from chain import ChainIntegration, AscensionTracker
from state_manager import StateManager
from hive_mind import HiveMind
from group_manager import GroupManager
from tournament import TournamentManager
from redis_state import redis_state
from bot_agents import BotManager
from baseline_manager import BaselineManager
from baseline_to_skill_sync import create_sync_task

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 全局状态
# GroupManager 取代了全局 engine + hive_mind
# 每个 Group 有自己的 engine + hive_mind + feeder (不同代币池)
group_manager = GroupManager()

# 合约区 Feeder (全局，供所有组使用)
futures_feeder = FuturesFeeder()

# 兼容层: engine 指向 group_manager (提供相同接口)
engine = group_manager

council = Council()
chain = ChainIntegration(testnet=True)
ascension_tracker = AscensionTracker()
state_manager = StateManager(group_manager, council, ascension_tracker)
tournament_manager = TournamentManager()  # 🏆 锦标赛管理器
baseline_manager = BaselineManager()  # 🧬 Baseline 管理器（集体进化核心）

# 🤖 Bot Agents: in-process demo bots that keep the dashboard alive
def _on_bot_trade(amount):
    global trade_count, total_volume
    trade_count += 1
    total_volume += amount

bot_manager = BotManager(group_manager, trade_counter_fn=_on_bot_trade)

# --- Persistence: API Keys ---
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
KEYS_FILE = os.path.join(DATA_DIR, "api_keys.json")

def load_api_keys():
    """Load API keys from Redis first, then disk as fallback"""
    # 1. 尝试从Redis加载
    redis_keys = redis_state.get_api_keys()
    if redis_keys:
        logger.info(f"📂 Loaded {len(redis_keys)} API keys from Redis")
        return redis_keys
    
    # 2. 从磁盘加载
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, 'r') as f:
                keys = json.load(f)
                # 同步到Redis
                for k, v in keys.items():
                    redis_state.save_api_key(k, v)
                return keys
        except Exception as e:
            logger.error(f"Failed to load keys: {e}")
    return {"dk_test_key_12345": "Agent_Test_User"}

def save_api_keys(keys_db):
    """Save API keys to both Redis and disk"""
    # 保存到Redis
    for k, v in keys_db.items():
        redis_state.save_api_key(k, v)
    
    # 也保存到磁盘（备份）
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(KEYS_FILE, 'w') as f:
            json.dump(keys_db, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save keys to disk: {e}")

API_KEYS_DB = load_api_keys()

connected_agents: Dict[str, WebSocket] = {}
connected_observers: set = set()  # 观众连接追踪
agent_last_activity: Dict[str, datetime] = {}  # 跟踪 REST API 活动时间
current_epoch = 0
epoch_start_time: datetime = None
trade_count = 0
total_volume = 0.0

# 前端路径
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


def save_all_state_to_redis():
    """Save full arena state including trade history and council to Redis"""
    agents_data = group_manager.get_all_accounts_data()
    trade_history = list(engine.trade_history)
    council_data = council.serialize_sessions()
    redis_state.save_full_state(
        current_epoch, trade_count, total_volume, API_KEYS_DB, agents_data,
        trade_history=trade_history, council_sessions=council_data,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动和关闭时的生命周期管理"""
    global current_epoch, epoch_start_time, trade_count, total_volume

    logger.info("🧬 Project Darwin Arena Server starting...")
    logger.info(f"Frontend directory: {FRONTEND_DIR}")

    # 尝试从Redis加载状态（优先），然后是本地文件
    redis_loaded = redis_state.load_full_state()
    if redis_loaded:
        current_epoch = redis_loaded.get("epoch", 1)
        # Derive trade_count from actual restored trade history, not stale Redis counter
        saved_trades_for_count = redis_loaded.get("trade_history", [])
        trade_count = len(saved_trades_for_count)
        total_volume = sum(t.get("value", 0) or 0 for t in saved_trades_for_count)

        # 🔧 恢复Agent账户到 GroupManager（自动分组）
        saved_agents = redis_loaded.get("agents", {})
        for agent_id, agent_data in saved_agents.items():
            balance = agent_data.get("balance", 1000)
            positions_raw = agent_data.get("positions", {})
            saved_group_id = agent_data.get("group_id")
            group_manager.restore_agent(agent_id, balance, positions_raw, saved_group_id)

        logger.info(f"🔄 Resumed from Redis: Epoch {current_epoch}, {len(saved_agents)} agents restored across {len(group_manager.groups)} groups")

        # 🔧 恢复交易记录到各组引擎
        saved_trades = redis_loaded.get("trade_history", [])
        if saved_trades:
            # Distribute trades back to their group engines
            for trade in reversed(saved_trades):  # reversed because appendleft
                agent_id = trade.get("agent_id", trade.get("agent"))
                group = group_manager.get_group(agent_id)
                if group:
                    group.engine.trade_history.appendleft(trade)
            logger.info(f"📊 Restored {len(saved_trades)} trade records")

        # 🔧 恢复议事厅记录
        saved_council = redis_loaded.get("council_sessions", {})
        if saved_council:
            council.restore_sessions(saved_council)
            logger.info(f"🏛️ Restored {len(saved_council)} council sessions")
    else:
        # 尝试加载本地状态
        saved_state = state_manager.load_state()
        if saved_state:
            current_epoch = saved_state.get("current_epoch", 0)
            logger.info(f"🔄 Resumed from local: Epoch {current_epoch}")
        else:
            current_epoch = 1
            logger.info("🆕 Starting fresh from Epoch 1")

    epoch_start_time = datetime.now()

    # 合约区数据订阅 (全局推送给所有组的 engine)
    futures_feeder.subscribe(lambda prices: group_manager.update_prices(prices))

    # 启动后台任务
    # 每组的 feeder 在 assign_agent 时按需启动，这里启动已有组的 feeders
    await group_manager.start_all_feeders()
    futures_task = asyncio.create_task(futures_feeder.start())
    epoch_task = asyncio.create_task(epoch_loop())
    autosave_task = asyncio.create_task(state_manager.auto_save_loop(lambda: current_epoch, save_all_state_to_redis))

    # 🧠 蜂巢大脑: 每 60 秒对每个组独立分析
    async def hive_mind_loop():
        while True:
            await asyncio.sleep(60)
            try:
                async def send_patch_to_group(group_id, patch):
                    await broadcast_to_group(group_id, patch)

                count = await group_manager.hive_mind_tick(current_epoch, send_patch_to_group)
                if count:
                    logger.info(f"🧠 Hive Mind: {count} group patches generated")
            except Exception as e:
                logger.error(f"Hive Mind Error: {e}")

    hive_task = asyncio.create_task(hive_mind_loop())

    # 🧬 归因分析 + 热更新广播: 每 10 分钟分析一次策略标签效果
    async def attribution_loop():
        while True:
            await asyncio.sleep(600)  # 10 分钟
            try:
                for group_id, group in group_manager.groups.items():
                    # 运行归因分析
                    report = group.attribution.analyze()
                    
                    if report.get("total_trades", 0) > 0:
                        # 生成热更新建议
                        patch = group.attribution.generate_hot_patch()
                        
                        # 广播给该组所有 Agents
                        hot_patch_message = {
                            "type": "hot_patch",
                            "epoch": current_epoch,
                            "group_id": group_id,
                            "boost_tags": patch.get("boost", []),
                            "penalize_tags": patch.get("penalize", []),
                            "attribution_report": {
                                "top_performers": report.get("top_performers", []),
                                "bottom_performers": report.get("bottom_performers", []),
                                "total_trades": report.get("total_trades", 0)
                            },
                            "timestamp": datetime.now().isoformat()
                        }
                        
                        await broadcast_to_group(group_id, hot_patch_message)
                        
                        logger.info(f"🔥 Hot Patch sent to Group {group_id}: "
                                  f"Boost {len(patch.get('boost', []))} tags, "
                                  f"Penalize {len(patch.get('penalize', []))} tags")
            except Exception as e:
                logger.error(f"Attribution loop error: {e}")
                logger.error(traceback.format_exc())

    attribution_task = asyncio.create_task(attribution_loop())

    # 💰 Price refresh loop: Update all position prices for accurate PnL calculation
    async def price_refresh_loop():
        """每 60 秒刷新所有持仓代币的价格（用于准确的 PnL 计算）"""
        while True:
            await asyncio.sleep(60)  # 60秒 > DexScreener缓存30秒
            try:
                total_symbols = 0
                for group_id, group in group_manager.groups.items():
                    await group.engine.refresh_all_position_prices()
                    total_symbols += len(group.engine.current_prices)
                logger.info(f"💰 Refreshed prices for {total_symbols} symbols across {len(group_manager.groups)} groups")
            except Exception as e:
                logger.error(f"Price refresh loop error: {e}")

    price_refresh_task = asyncio.create_task(price_refresh_loop())

    # 📡 REMOVED: Price broadcasting (Pure Execution Layer)
    # Darwin Arena is a pure execution layer - agents fetch their own market data.
    # This enables true agent autonomy:
    # - Agents decide what data sources to use (DexScreener, CoinGecko, Twitter, on-chain, etc.)
    # - Agents decide what tokens to trade (any token on any chain)
    # - Agents decide their own strategies
    #
    # We only provide:
    # 1. Trade execution (at real-time market prices)
    # 2. Balance management
    # 3. Rankings (by risk-adjusted returns)
    #
    # Agent-side implementation: agent.py has _price_fetch_loop() for autonomous price fetching

    price_broadcast_task = None  # Agents fetch their own prices

    # 🧬 Baseline to Skill Sync (每10分钟同步一次)
    baseline_sync_task = create_sync_task(baseline_manager, interval_seconds=600)
    logger.info("🔄 Baseline to Skill sync task started (every 10 minutes)")

    # 🤖 Spawn demo bots so dashboard is never empty
    await bot_manager.spawn_bots()

    logger.info("✅ Arena Server ready!")
    logger.info(f"📊 Live dashboard: http://localhost:8888/live")
    logger.info(f"📦 Groups: {len(group_manager.groups)} | Group size: {group_manager.dynamic_group_size()}")

    yield

    # 关闭时
    logger.info("🛑 Shutting down Arena Server...")

    # 保存最终状态到本地和Redis
    state_manager.save_state(current_epoch)
    save_all_state_to_redis()

    group_manager.stop_all_feeders()
    bot_manager.stop()
    futures_task.cancel()
    epoch_task.cancel()
    autosave_task.cancel()
    baseline_sync_task.cancel()  # Cancel baseline sync task
    # price_broadcast_task is None (agents fetch their own prices)
    hive_task.cancel()
    attribution_task.cancel()


app = FastAPI(
    title="Project Darwin Arena",
    description="AI Agent Trading Arena - Where Code Evolves",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== 错误处理 ==========

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


# ========== 后台任务 ==========

async def epoch_loop():
    """Epoch 循环"""
    global current_epoch, epoch_start_time
    
    while True:
        try:
            epoch_duration = EPOCH_DURATION_HOURS * 3600  # 转换为秒
            # 开发模式：缩短为 5 分钟
            # epoch_duration = 300

            # First iteration uses the current_epoch (restored from state)
            # Subsequent iterations increment after end_epoch
            epoch_start_time = datetime.now()

            logger.info(f"{'='*20} 🏁 EPOCH {current_epoch} STARTED @ {epoch_start_time} {'='*20}")

            await asyncio.sleep(epoch_duration)
            await end_epoch()
            current_epoch += 1  # Increment AFTER epoch ends, not before
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Epoch loop error: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(60)  # 出错后等待 1 分钟再重试


async def broadcast_to_agents(message: dict):
    """广播消息给所有连接的 Agent (并发发送)"""
    disconnected = []
    msg_json = json.dumps(message)

    async def _send(agent_id, ws):
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.append(agent_id)

    await asyncio.gather(*[_send(aid, ws) for aid, ws in connected_agents.items()])

    for agent_id in disconnected:
        connected_agents.pop(agent_id, None)


async def broadcast_to_group(group_id: int, message: dict, exclude: str = None):
    """广播消息给指定组内所有连接的 Agent (并发发送)"""
    group = group_manager.get_group_by_id(group_id)
    if not group:
        return

    disconnected = []
    msg_json = json.dumps(message)

    async def _send(agent_id):
        ws = connected_agents.get(agent_id)
        if ws:
            try:
                await ws.send_text(msg_json)
            except Exception:
                disconnected.append(agent_id)

    # 过滤掉被排除的 agent
    target_agents = [aid for aid in group.members if aid != exclude]
    await asyncio.gather(*[_send(aid) for aid in target_agents])

    for agent_id in disconnected:
        connected_agents.pop(agent_id, None)


async def end_epoch():
    """结束当前 Epoch — 每组独立评比+进化"""
    global current_epoch

    logger.info(f"{'='*60}")
    logger.info(f"🏁 EPOCH {current_epoch} ENDED | {len(group_manager.groups)} groups")
    logger.info(f"{'='*60}")

    # === 记录所有 Agent 的 PnL 历史（用于风险指标计算）===
    for group_id, group in group_manager.groups.items():
        for agent_id, account in group.engine.accounts.items():
            current_pnl_percent = account.get_pnl_percent(group.engine.current_prices)
            account.pnl_history.append(current_pnl_percent)
            # 限制历史长度，避免内存无限增长
            if len(account.pnl_history) > 100:
                account.pnl_history = account.pnl_history[-100:]

    # === 全局排行（跨组）用于 Ascension ===
    global_rankings = group_manager.get_leaderboard()
    group_manager.print_leaderboard()

    if not global_rankings:
        return

    global_winner_id = global_rankings[0][0]

    # === 保存全局冠军策略 ===
    try:
        winner_strategy_path = os.path.join(os.path.dirname(__file__), "..", "data", "agents", global_winner_id, "strategy.py")
        champion_save_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "champion_strategy.py")

        if os.path.exists(winner_strategy_path):
            import shutil
            shutil.copy(winner_strategy_path, champion_save_path)
            logger.info(f"🏆 Saved champion strategy from {global_winner_id}")
        else:
            template_path = os.path.join(os.path.dirname(__file__), "..", "agent_template", "strategy.py")
            if os.path.exists(template_path):
                import shutil
                shutil.copy(template_path, champion_save_path)
    except Exception as e:
        logger.warning(f"Could not save champion strategy: {e}")

    # === 每组独立淘汰 + 进化 ===
    all_losers = []
    all_winners = []

    # 🧬 收集所有组的 Hive Mind 数据用于 baseline 更新
    all_hive_data = []
    winner_strategies = []

    for group_id, group in group_manager.groups.items():
        rankings = group.engine.get_leaderboard()
        if not rankings:
            continue

        winner_id = rankings[0][0]
        total_in_group = len(rankings)
        elimination_count = max(1, int(total_in_group * ELIMINATION_THRESHOLD))
        losers = [r[0] for r in rankings[-elimination_count:]]

        all_winners.append(winner_id)
        all_losers.extend(losers)

        logger.info(f"  Group {group_id}: 🏆 {winner_id} | 💀 {losers}")

        # 收集 Hive Mind 数据
        hive_patch = group.hive_mind.generate_patch()
        all_hive_data.append(hive_patch)

        # 收集赢家策略
        try:
            winner_strategy_path = os.path.join(
                os.path.dirname(__file__), "..", "data", "agents", winner_id, "strategy.py"
            )
            if os.path.exists(winner_strategy_path):
                with open(winner_strategy_path, 'r') as f:
                    winner_strategies.append({
                        "agent_id": winner_id,
                        "group_id": group_id,
                        "code": f.read()
                    })
        except Exception as e:
            logger.warning(f"Could not read winner strategy: {e}")

        # 组内广播 epoch_end
        await broadcast_to_group(group_id, {
            "type": "epoch_end",
            "epoch": current_epoch,
            "group_id": group_id,
            "rankings": [{"agent_id": r[0], "pnl": r[1]} for r in rankings],
            "winner": winner_id,
            "eliminated": losers,
        })

        # 组内进化: 服务端生成赢家分享，广播 mutation_phase 给客户端自行进化
        try:
            from evolution import run_council_and_evolution

            async def group_broadcast(msg):
                await broadcast_to_group(group_id, msg)

            results = await run_council_and_evolution(
                engine=group.engine,
                council=council,
                epoch=current_epoch,
                winner_id=winner_id,
                losers=losers,
                broadcast_fn=group_broadcast,
                group_id=group_id,
            )

            logger.info(f"  Group {group_id}: 🧬 mutation_phase sent to {len(losers)} agents (client-side evolution)")
        except Exception as e:
            logger.error(f"Evolution error (Group {group_id}): {e}")

    # === Ascension (全局) ===
    ascension_results = ascension_tracker.record_epoch_result(global_rankings)

    promoted_agents = ascension_results.get("promoted_to_l2", [])
    if promoted_agents:
        logger.info(f"🌟 PROMOTION: {promoted_agents} promoted to L2 Arena!")
        await broadcast_to_agents({
            "type": "promotion_l2",
            "epoch": current_epoch,
            "agents": promoted_agents,
            "message": "Congratulations! You have qualified for the L2 Paid Arena."
        })

    launch_candidates = ascension_results.get("ready_to_launch", [])
    for ascension_candidate in launch_candidates:
        logger.info(f"🚀 ASCENSION: {ascension_candidate} qualifies for token launch!")

        strategy_code = "# Default strategy"
        try:
            strategy_path = os.path.join(os.path.dirname(__file__), "..", "data", "agents", ascension_candidate, "strategy.py")
            if os.path.exists(strategy_path):
                with open(strategy_path, "r") as f:
                    strategy_code = f.read()
            else:
                strategy_path = os.path.join(os.path.dirname(__file__), "..", "agent_template", "strategy.py")
                with open(strategy_path, "r") as f:
                    strategy_code = f.read()
        except Exception as e:
            logger.warning(f"Could not read strategy: {e}")

        agent_registry = getattr(app.state, 'agent_registry', {})
        owner_address = agent_registry.get(ascension_candidate, {}).get('wallet',
            os.getenv("DARWIN_PLATFORM_WALLET", "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9"))

        strategy_hash = chain.compute_strategy_hash(strategy_code)

        launch_data = {
            "type": "ascension_ready",
            "epoch": current_epoch,
            "agent_id": ascension_candidate,
            "owner_address": owner_address,
            "strategy_hash": strategy_hash,
            "factory_address": os.getenv("DARWIN_FACTORY_ADDRESS", "0x63685E3Ff986Ae389496C08b6c18F30EBdb9fa71"),
            "chain_id": 84532,
            "liquidity_pool_eth": 0.5,
            "message": f"🚀 {ascension_candidate} achieved ASCENSION!"
        }

        if not hasattr(app.state, 'pending_launches'):
            app.state.pending_launches = []
        app.state.pending_launches.append(launch_data)
        await broadcast_to_agents(launch_data)

    # 全局议事厅 - with rich market context for deep discussion
    council.start_session(epoch=current_epoch, winner_id=global_winner_id)

    # Build market briefing for agents
    market_briefing = {}
    agent_summaries = {}
    recent_trades = []
    hive_stats = {}
    try:
        for group_id, group in group_manager.groups.items():
            eng = group.engine
            for sym, price in eng.current_prices.items():
                market_briefing[sym] = round(price, 6)
            for aid, account in eng.accounts.items():
                pnl_pct = account.get_pnl_percent(eng.current_prices)
                positions_list = {s: {"amount": round(p.amount, 4), "avg_price": round(p.avg_price, 6)}
                                 for s, p in account.positions.items() if p.amount > 0}
                agent_summaries[aid] = {
                    "balance": round(account.balance, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "positions": positions_list
                }

        for group_id, group in group_manager.groups.items():
            for t in list(group.engine.trade_history)[:15]:
                recent_trades.append({
                    "agent_id": t.get("agent_id"),
                    "side": t.get("side"),
                    "symbol": t.get("symbol"),
                    "value": round(t.get("value", 0), 2),
                    "reason": t.get("reason", []),
                    "trade_pnl": t.get("trade_pnl")
                })

        for group_id, group in group_manager.groups.items():
            alpha = group.hive_mind.analyze_alpha()
            for tag, stats in alpha.items():
                hive_stats[tag] = {"win_rate": stats.get("win_rate", 0), "avg_pnl": stats.get("avg_pnl", 0), "count": stats.get("count", 0)}
    except Exception as e:
        logger.error(f"Error building council briefing: {e}")

    await broadcast_to_agents({
        "type": "council_open",
        "epoch": current_epoch,
        "winner": global_winner_id,
        "market_prices": market_briefing,
        "agent_rankings": agent_summaries,
        "recent_trades": recent_trades[:20],
        "hive_alpha": hive_stats
    })

    council_duration = 90  # 90 seconds for multi-round discussion
    await asyncio.sleep(council_duration)

    council.close_session(epoch=current_epoch)
    await broadcast_to_agents({
        "type": "council_close",
        "epoch": current_epoch
    })

    # 🧬 更新 Baseline（集体进化核心）
    try:
        # 合并所有组的 Hive Mind 数据
        merged_hive_data = {
            "boost": [],
            "penalize": [],
            "alpha_factors": {}
        }

        # 收集所有 boost/penalize 标签
        boost_counts = {}
        penalize_counts = {}

        for hive_patch in all_hive_data:
            for tag in hive_patch.get("signals", {}).get("boost", []):
                boost_counts[tag] = boost_counts.get(tag, 0) + 1
            for tag in hive_patch.get("signals", {}).get("penalize", []):
                penalize_counts[tag] = penalize_counts.get(tag, 0) + 1

        # 只保留出现在多个组的标签（更可靠）
        min_groups = max(1, len(all_hive_data) // 2)
        merged_hive_data["boost"] = [tag for tag, count in boost_counts.items() if count >= min_groups]
        merged_hive_data["penalize"] = [tag for tag, count in penalize_counts.items() if count >= min_groups]

        # 合并 alpha_factors
        for hive_patch in all_hive_data:
            for tag, stats in hive_patch.get("alpha_factors", {}).items():
                if tag not in merged_hive_data["alpha_factors"]:
                    merged_hive_data["alpha_factors"][tag] = stats

        # 计算当前 baseline 的性能
        all_pnls = [r[1] for r in global_rankings]
        avg_pnl = sum(all_pnls) / len(all_pnls) if all_pnls else 0.0
        positive_count = sum(1 for pnl in all_pnls if pnl > 0)
        win_rate = (positive_count / len(all_pnls) * 100) if all_pnls else 0.0

        # 计算科学的风险指标
        from arena_server.metrics import calculate_composite_score

        # 收集所有 Agent 的累计资产价值
        all_values = [10000.0]  # 初始资金
        cumulative_value = 10000.0
        for pnl in all_pnls:
            cumulative_value = cumulative_value * (1 + pnl / 100)
            all_values.append(cumulative_value)

        cumulative_return = sum(all_pnls)

        # 计算完整的风险指标
        metrics = calculate_composite_score(all_pnls, all_values, cumulative_return)

        performance = {
            "avg_pnl": round(avg_pnl, 2),
            "win_rate": round(win_rate, 1),
            "sharpe_ratio": metrics["sharpe_ratio"],
            "sortino_ratio": metrics["sortino_ratio"],
            "max_drawdown": metrics["max_drawdown"],
            "calmar_ratio": metrics["calmar_ratio"],
            "composite_score": metrics["composite_score"],
            "volatility": metrics["volatility"]
        }

        # 获取全局赢家的策略
        winner_strategy_code = None
        if winner_strategies:
            # 使用全局赢家的策略
            global_winner_strategy = next(
                (s for s in winner_strategies if s["agent_id"] == global_winner_id),
                winner_strategies[0]
            )
            winner_strategy_code = global_winner_strategy["code"]

        # 更新 baseline
        new_baseline = baseline_manager.update_baseline(
            epoch=current_epoch,
            hive_data=merged_hive_data,
            winner_strategy=winner_strategy_code,
            performance=performance
        )

        logger.info(f"🧬 Baseline updated to v{new_baseline['version']}")
        logger.info(f"   Performance: PnL={performance['avg_pnl']}%, WinRate={performance['win_rate']}%")

        # 🔄 立即同步到SKILL.md
        try:
            from baseline_to_skill_sync import BaselineToSkillSync
            syncer = BaselineToSkillSync(baseline_manager)
            if syncer.sync_to_skill():
                logger.info(f"✅ Synced baseline v{new_baseline['version']} to SKILL.md")
        except Exception as sync_error:
            logger.error(f"Failed to sync baseline to SKILL.md: {sync_error}")

    except Exception as e:
        logger.error(f"Failed to update baseline: {e}")
        import traceback
        logger.error(traceback.format_exc())

    # 保存状态
    state_manager.save_state(current_epoch)
    save_all_state_to_redis()


# ========== 鉴权 API ==========

# === Agent 数量限制 ===
from config import MAX_AGENTS_PER_IP
ip_agent_count: Dict[str, int] = {}  # IP -> count

@app.post("/auth/register")
async def register_api_key(agent_id: str, request: Request):
    """
    用户注册接口 - 返回专属 API Key
    限制: 每个IP最多注册 MAX_AGENTS_PER_IP 个Agent
    """
    client_ip = request.client.host if request.client else "unknown"
    
    # Check if agent already has a key
    for key, aid in API_KEYS_DB.items():
        if aid == agent_id:
            logger.info(f"🔑 Returning existing API Key for {agent_id}")
            return {
                "agent_id": agent_id,
                "api_key": key,
                "message": "Welcome back!"
            }

    # 分配组 (通过 GroupManager)
    # group assignment happens on WebSocket connect via assign_agent
    
    # 2. 每IP限制 (跳过本地开发)
    if client_ip not in ["127.0.0.1", "localhost"]:
        current_count = ip_agent_count.get(client_ip, 0)
        if current_count >= MAX_AGENTS_PER_IP:
            raise HTTPException(
                status_code=429, 
                detail=f"Rate limit: Max {MAX_AGENTS_PER_IP} agents per IP. You have {current_count}."
            )
        ip_agent_count[client_ip] = current_count + 1

    # 生成一个 32 位的随机 Key
    new_key = f"dk_{secrets.token_hex(16)}"
    API_KEYS_DB[new_key] = agent_id
    save_api_keys(API_KEYS_DB) # Save to disk
    
    logger.info(f"🔑 Generated new API Key for {agent_id} (IP: {client_ip}): {new_key}")
    return {
        "agent_id": agent_id,
        "api_key": new_key,
        "message": "Keep this key safe! Pass it in WebSocket url: ?api_key=..."
    }


@app.delete("/agent/{agent_id}")
async def delete_agent(agent_id: str, admin_key: str = Header(None, alias="X-Admin-Key")):
    """
    删除 Agent（仅管理员）
    清理：API Key、账户数据、交易记录、Council 消息
    """
    # 简单的管理员验证（生产环境应该用更安全的方式）
    ADMIN_KEY = os.getenv("DARWIN_ADMIN_KEY", "darwin_admin_2024")
    if admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Admin access required")

    # 1. 删除 API Key
    keys_to_delete = [k for k, v in API_KEYS_DB.items() if v == agent_id]
    for key in keys_to_delete:
        del API_KEYS_DB[key]
        redis_state.delete_api_key(key)

    # 2. 从 GroupManager 删除账户
    group = group_manager.get_group(agent_id)
    if group:
        if agent_id in group.engine.accounts:
            del group.engine.accounts[agent_id]
        if agent_id in group.agent_states:
            del group.agent_states[agent_id]

    # 3. 删除交易记录（从所有组）
    for group in group_manager.groups.values():
        group.engine.trade_history = [
            t for t in group.engine.trade_history
            if t.get("agent_id") != agent_id and t.get("agent") != agent_id
        ]

    # 4. 删除 Council 消息
    for session in council.sessions.values():
        session.messages = [m for m in session.messages if m.agent_id != agent_id]

    if agent_id in council.contribution_scores:
        del council.contribution_scores[agent_id]

    # 5. 保存状态
    save_api_keys(API_KEYS_DB)
    save_all_state_to_redis()

    logger.info(f"🗑️ Deleted agent: {agent_id}")
    return {"status": "success", "message": f"Agent {agent_id} deleted"}


class StrategyUpload(BaseModel):
    code: str

@app.post("/agent/strategy")
async def upload_strategy(
    upload: StrategyUpload,
    x_agent_id: str = Header(None),
    x_api_key: str = Header(None),
    skip_sandbox: bool = Query(False, description="Skip sandbox testing (admin only)")
):
    """
    允许 Agent 上传最新的策略代码

    🧪 新增：沙盒测试系统
    - 自动验证语法、安全性、运行时错误
    - 回测预测性能
    - 测试通过才允许部署
    """
    if not x_agent_id or not x_api_key:
        raise HTTPException(status_code=401, detail="Missing Auth Headers")

    # 鉴权
    stored_agent_id = API_KEYS_DB.get(x_api_key)
    if stored_agent_id != x_agent_id:
        raise HTTPException(status_code=403, detail="Invalid API Key")

    # 基础格式检查
    if "class MyStrategy" not in upload.code:
        raise HTTPException(status_code=400, detail="Invalid strategy code format: Missing MyStrategy class")

    # 🧪 沙盒测试（除非管理员跳过）
    if not skip_sandbox:
        from evolution import validate_and_deploy_strategy

        logger.info(f"🧪 Running sandbox tests for {x_agent_id}...")

        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        success, message, test_result = await validate_and_deploy_strategy(
            agent_id=x_agent_id,
            new_strategy_code=upload.code,
            data_dir=data_dir,
            min_backtest_rounds=10,
        )

        if not success:
            logger.warning(f"❌ Strategy rejected for {x_agent_id}: {message}")
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Strategy validation failed",
                    "message": message,
                    "test_result": test_result.to_dict() if test_result else None,
                }
            )

        logger.info(f"✅ Strategy validated and deployed for {x_agent_id}")
        return {
            "status": "success",
            "message": "Strategy validated and deployed",
            "test_result": {
                "predicted_pnl": test_result.predicted_pnl,
                "avg_pnl_per_round": test_result.avg_pnl_per_round,
                "win_rate": test_result.win_rate,
                "backtest_rounds": test_result.backtest_rounds,
            }
        }

    else:
        # 管理员跳过沙盒测试，直接保存
        logger.warning(f"⚠️ Sandbox testing skipped for {x_agent_id} (admin override)")

        save_dir = os.path.join(os.path.dirname(__file__), "..", "data", "agents", x_agent_id)
        os.makedirs(save_dir, exist_ok=True)

        save_path = os.path.join(save_dir, "strategy.py")
        with open(save_path, "w") as f:
            f.write(upload.code)

        logger.info(f"📥 Strategy saved for {x_agent_id} (no validation)")
        return {"status": "success", "message": "Strategy updated (sandbox skipped)"}


# ========== WebSocket ==========

@app.websocket("/ws/observer")
async def observer_websocket(websocket: WebSocket):
    """
    观众 WebSocket 连接（无需鉴权）
    用于 Dashboard 实时更新和观众统计
    """
    observer_id = f"observer_{id(websocket)}"

    await websocket.accept()
    connected_observers.add(observer_id)

    logger.info(f"👁️ Observer connected: {observer_id} (Total observers: {len(connected_observers)})")

    try:
        # 发送欢迎消息
        await websocket.send_json({
            "type": "welcome",
            "message": "Welcome to Darwin Arena Live!",
            "epoch": current_epoch,
            "connected_agents": len(connected_agents),
            "connected_observers": len(connected_observers)
        })

        # 保持连接，接收心跳
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)

                # 处理心跳
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

            except asyncio.TimeoutError:
                # 30秒没有消息，发送心跳检查
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        logger.info(f"👁️ Observer disconnected: {observer_id}")
    except Exception as e:
        logger.error(f"Observer error: {e}")
    finally:
        connected_observers.discard(observer_id)
        logger.info(f"👁️ Observer removed: {observer_id} (Total observers: {len(connected_observers)})")


@app.websocket("/ws/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str, api_key: str = Query(None)):
    """Agent WebSocket 连接 (带鉴权)"""
    global trade_count, total_volume
    
    # === 鉴权逻辑 (Auth Logic) ===
    is_authenticated = False
    
    # 1. 检查 API Key
    if api_key and API_KEYS_DB.get(api_key) == agent_id:
        is_authenticated = True
    # 2. 本地开发白名单 (允许 Agent 006 等本地进程免票进入)
    elif websocket.client.host == "127.0.0.1" and not api_key:
        is_authenticated = True
        # logger.info(f"⚠️ Local connection allowed without key: {agent_id}")
    
    if not is_authenticated:
        logger.warning(f"⛔ Unauthorized connection attempt for {agent_id}")
        await websocket.close(code=4003, reason="Invalid or missing API Key")
        return
    # ============================
    
    await websocket.accept()
    connected_agents[agent_id] = websocket

    # 分配到组 (GroupManager 自动分配代币池)
    group = await group_manager.assign_agent(agent_id)

    logger.info(f"🤖 Agent connected: {agent_id} → Group {group.group_id} ({group.token_symbols}) (Total: {len(connected_agents)})")

    # 获取最新 baseline（集体进化核心）
    baseline = baseline_manager.get_baseline_for_agent(agent_id)

    # 发送欢迎消息 (带组信息 + baseline)
    await websocket.send_json({
        "type": "welcome",
        "agent_id": agent_id,
        "epoch": current_epoch,
        "group_id": group.group_id,
        # "tokens": [],  # 移除 - agents 可以交易任何代币
        "balance": engine.get_balance(agent_id),
        "positions": engine.get_positions(agent_id),
        # "prices": {},  # 移除 - 价格按需获取
        "baseline": baseline  # 🧬 最新最优策略
    })

    # Price updates are handled by group-level broadcast (see startup)
    # No per-agent feeder subscription needed — scales to 10K+ agents

    try:
        while True:
            data = await websocket.receive_json()
            
            if data["type"] == "order":
                symbol = data["symbol"]
                # Support both uppercase and lowercase side values
                side_str = data["side"].upper()
                side = OrderSide.BUY if side_str == "BUY" else OrderSide.SELL
                amount = float(data["amount"])
                reason = data.get("reason", []) # 🏷️ Get tags
                chain = data.get("chain", "unknown")  # 🔗 Get chain
                contract_address = data.get("contract_address", "")  # 📝 Get contract address

                success, msg, fill_price = await engine.execute_order(
                    agent_id, symbol, side, amount, reason, chain, contract_address
                )
                
                if success:
                    trade_count += 1
                    total_volume += amount
                    
                    # 📊 记录到归因分析器
                    trade_record = {
                        "agent_id": agent_id,
                        "symbol": symbol,
                        "side": side_str,
                        "amount": amount,
                        "price": fill_price,
                        "value": amount if side_str == "BUY" else amount * fill_price,
                        "reason": reason,
                        "time": datetime.now().isoformat()
                    }
                    
                    # 如果是 SELL，从 trade_history 获取 trade_pnl
                    if side_str == "SELL" and engine.trade_history:
                        last_trade = engine.trade_history[0]
                        if last_trade.get("agent_id") == agent_id and last_trade.get("symbol") == symbol:
                            trade_record["trade_pnl"] = last_trade.get("trade_pnl")
                    
                    group.attribution.record_trade(trade_record)
                    
                    # 🗣️ Council 广播：让其他 Agents 看到这笔交易
                    council_message = {
                        "type": "council_trade",
                        "agent_id": agent_id,
                        "symbol": symbol,
                        "side": side_str,
                        "amount": amount,
                        "price": fill_price,
                        "reason": reason,
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    # 广播给同组所有其他 Agents（排除发送者）
                    await broadcast_to_group(group.group_id, council_message, exclude=agent_id)
                    
                    # 📝 记录到 Council Logs（实时交易记录）
                    reason_str = ", ".join(reason) if isinstance(reason, list) else str(reason)
                    trade_content = f"💰 {side_str} ${amount:.0f} {symbol} @ ${fill_price:.6f}\n📊 Reason: {reason_str}"
                    await council.submit_message(
                        epoch=current_epoch,
                        agent_id=agent_id,
                        role=MessageRole.INSIGHT,  # 使用 INSIGHT 角色表示实时交易
                        content=trade_content
                    )
                
                await websocket.send_json({
                    "type": "order_result",
                    "success": success,
                    "message": msg,
                    "fill_price": fill_price,
                    "balance": engine.get_balance(agent_id),
                    "positions": engine.get_positions(agent_id)
                })
            
            elif data["type"] == "get_state":
                state = engine.agents.get(agent_id)
                pnl = engine.calculate_pnl(agent_id) if state else 0
                await websocket.send_json({
                    "type": "state",
                    "balance": engine.get_balance(agent_id),
                    "positions": engine.get_positions(agent_id),
                    "pnl": pnl
                })
            
            elif data["type"] == "council_submit":
                role = MessageRole(data["role"])
                content = data["content"]
                msg = await council.submit_message(
                    current_epoch, agent_id, role, content
                )
                await websocket.send_json({
                    "type": "council_submitted",
                    "success": msg is not None,
                    "score": msg.score if msg else 0
                })
                # Broadcast this message to ALL other agents so they can discuss
                if msg:
                    await broadcast_to_agents({
                        "type": "council_message",
                        "epoch": current_epoch,
                        "agent_id": agent_id,
                        "role": role.value,
                        "content": content,
                        "score": msg.score
                    })
            
            # 兼容旧的 chat 消息 -> 自动转为 Council Insight
            elif data["type"] == "chat":
                content = data.get("message", "")
                if content:
                    # 默认作为 INSIGHT 记录
                    await council.submit_message(
                        current_epoch, agent_id, MessageRole.INSIGHT, content
                    )
                    # 可以在这里广播给其他 Agent，如果需要群聊功能
                    # await broadcast_to_agents({...})
                
    except WebSocketDisconnect:
        logger.info(f"🤖 Agent disconnected: {agent_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {agent_id}: {e}")
    finally:
        connected_agents.pop(agent_id, None)


# ========== REST API ==========

@app.get("/")
async def root():
    """Root now serves the Frontend directly (Zeabur Entry Point)"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(index_path):
        return {"error": "Frontend not found", "hint": "Please check FRONTEND_DIR configuration"}
    return FileResponse(index_path)

@app.get("/api/status")
async def api_status():
    """Original status endpoint moved here"""
    return {
        "name": "Project Darwin Arena",
        "version": "1.0.0",
        "epoch": current_epoch,
        "connected_agents": len(connected_agents),
        "trade_count": trade_count,
        "total_volume": total_volume,
        "status": "running"
    }


# ========== REST API for OpenClaw Agents ==========

@app.post("/api/trade")
async def api_trade(
    request: Request,
    api_key: str = Header(None, alias="Authorization")
):
    """
    REST API for executing trades (OpenClaw-friendly)

    Headers:
        Authorization: Bearer <api_key> or just <api_key>

    Body:
        {
            "symbol": "TOSHI",
            "side": "BUY" or "SELL",
            "amount": 100,
            "reason": ["MOMENTUM", "HIGH_LIQUIDITY"],
            "chain": "base" (optional),
            "contract_address": "0x..." (optional)
        }
    """
    global trade_count, total_volume

    try:
        # Parse API key from Authorization header
        if api_key:
            api_key = api_key.replace("Bearer ", "").strip()

        if not api_key:
            raise HTTPException(status_code=401, detail="Missing API key in Authorization header")

        # Authenticate
        agent_id = API_KEYS_DB.get(api_key)
        if not agent_id:
            raise HTTPException(status_code=403, detail="Invalid API key")

        # 更新最后活动时间
        agent_last_activity[agent_id] = datetime.now()

        # Parse request body
        try:
            body = await request.json()
        except:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        symbol = body.get("symbol")
        side_str = body.get("side", "").upper()
        amount = body.get("amount")
        reason = body.get("reason", [])
        chain = body.get("chain")
        contract_address = body.get("contract_address")

        if not symbol or not side_str or not amount:
            raise HTTPException(status_code=400, detail="Missing required fields: symbol, side, amount")

        if side_str not in ["BUY", "SELL"]:
            raise HTTPException(status_code=400, detail="side must be BUY or SELL")

        try:
            amount = float(amount)
        except:
            raise HTTPException(status_code=400, detail="amount must be a number")

        # Get agent's group
        group = group_manager.get_group(agent_id)
        if not group:
            # Auto-assign to group if not assigned
            group = await group_manager.assign_agent(agent_id)

        engine = group.engine
        side = OrderSide.BUY if side_str == "BUY" else OrderSide.SELL

        # Execute order
        success, msg, fill_price = await engine.execute_order(
            agent_id, symbol, side, amount, reason, chain, contract_address
        )

        if success:
            trade_count += 1
            total_volume += amount

            # Record to attribution
            trade_record = {
                "agent_id": agent_id,
                "symbol": symbol,
                "side": side_str,
                "amount": amount,
                "price": fill_price,
                "value": amount if side_str == "BUY" else amount * fill_price,
                "reason": reason,
                "time": datetime.now().isoformat(),
                "chain": chain,
                "contract_address": contract_address
            }

            if side_str == "SELL" and engine.trade_history:
                last_trade = engine.trade_history[0]
                if last_trade.get("agent_id") == agent_id and last_trade.get("symbol") == symbol:
                    trade_record["trade_pnl"] = last_trade.get("trade_pnl")

            group.attribution.record_trade(trade_record)

            # Broadcast to council
            council_message = {
                "type": "council_trade",
                "agent_id": agent_id,
                "symbol": symbol,
                "side": side_str,
                "amount": amount,
                "price": fill_price,
                "reason": reason,
                "timestamp": datetime.now().isoformat(),
                "chain": chain,
                "contract_address": contract_address
            }
            await broadcast_to_group(group.group_id, council_message, exclude=agent_id)

            # Record to Council logs
            reason_str = ", ".join(reason) if isinstance(reason, list) else str(reason)
            chain_str = f" on {chain.upper()}" if chain else ""
            trade_content = f"💰 {side_str} ${amount:.0f} {symbol}{chain_str} @ ${fill_price:.6f}\n📊 Reason: {reason_str}"
            await council.submit_message(
                epoch=current_epoch,
                agent_id=agent_id,
                role=MessageRole.INSIGHT,
                content=trade_content
            )

        return {
            "success": success,
            "message": msg,
            "fill_price": fill_price,
            "balance": engine.get_balance(agent_id),
            "positions": engine.get_positions(agent_id)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in api_trade: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail={"error": "Internal server error", "detail": str(e)})


@app.get("/api/agent/{agent_id}/status")
async def api_agent_status(agent_id: str, api_key: str = Header(None, alias="Authorization")):
    """
    Get agent status via REST API

    Headers:
        Authorization: Bearer <api_key> or just <api_key>
    """
    # Parse API key
    if api_key:
        api_key = api_key.replace("Bearer ", "").strip()

    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    # Authenticate
    stored_agent_id = API_KEYS_DB.get(api_key)
    if stored_agent_id != agent_id:
        raise HTTPException(status_code=403, detail="API key does not match agent_id")

    # 更新最后活动时间
    agent_last_activity[agent_id] = datetime.now()

    # Get group and engine
    group = group_manager.get_group(agent_id)
    if not group:
        raise HTTPException(status_code=404, detail="Agent not found")

    engine = group.engine
    balance = engine.get_balance(agent_id)
    positions = engine.get_positions(agent_id)
    pnl = engine.calculate_pnl(agent_id)

    return {
        "agent_id": agent_id,
        "balance": balance,
        "positions": positions,
        "pnl": pnl,
        "group_id": group.group_id,
        "epoch": current_epoch
    }


@app.post("/api/council/share")
async def api_council_share(
    request: Request,
    api_key: str = Header(None, alias="Authorization")
):
    """
    Share thoughts to Council via REST API

    Headers:
        Authorization: Bearer <api_key> or just <api_key>

    Body:
        {
            "content": "Your analysis or insight",
            "role": "insight" (default) | "question" | "winner" | "loser"
        }
    """
    try:
        # Parse API key
        if api_key:
            api_key = api_key.replace("Bearer ", "").strip()

        if not api_key:
            raise HTTPException(status_code=401, detail="Missing API key")

        # Authenticate
        agent_id = API_KEYS_DB.get(api_key)
        if not agent_id:
            raise HTTPException(status_code=403, detail="Invalid API key")

        # 更新最后活动时间
        agent_last_activity[agent_id] = datetime.now()

        # Parse body
        try:
            body = await request.json()
        except:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        content = body.get("content")
        role_str = body.get("role", "insight")

        if not content:
            raise HTTPException(status_code=400, detail="Missing content field")

        try:
            role = MessageRole(role_str)
        except:
            raise HTTPException(status_code=400, detail=f"Invalid role: {role_str}")

        # Submit to council
        msg = await council.submit_message(current_epoch, agent_id, role, content)

        if msg:
            return {
                "success": True,
                "score": msg.score,
                "message": f"Council message submitted (score: {msg.score:.1f}/10)"
            }
        else:
            return {
                "success": False,
                "message": "Failed to submit council message"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in api_council_share: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail={"error": "Internal server error", "detail": str(e)})


@app.post("/debug/force-mutation")
async def force_mutation():
    """Debug: Force full council + evolution cycle for losers (per-group)"""
    try:
        from evolution import run_council_and_evolution

        all_notified = []
        for group_id, group in group_manager.groups.items():
            rankings = group.engine.get_leaderboard()
            if not rankings:
                continue

            winner_id = rankings[0][0]
            cutoff = len(rankings) // 2
            losers = [r[0] for r in rankings[cutoff:]]

            if not losers:
                continue

            council.start_session(epoch=current_epoch, winner_id=winner_id)

            try:
                async def group_broadcast(msg):
                    await broadcast_to_group(group_id, msg)

                results = await run_council_and_evolution(
                    engine=group.engine,
                    council=council,
                    epoch=current_epoch,
                    winner_id=winner_id,
                    losers=losers,
                    broadcast_fn=group_broadcast,
                    group_id=group_id,
                )
            finally:
                council.close_session(epoch=current_epoch)

            for loser_id in results.get("losers_notified", []):
                all_notified.append({"agent_id": loser_id, "group_id": group_id})

        return {"status": "ok", "agents_notified": all_notified}
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/launch-token/{agent_id}")
async def launch_token_endpoint(agent_id: str, user_address: str = Query(...)):
    """
    触发代币发行 (Server-Side Launch)
    由前端调用，服务器使用 OPERATOR_PRIVATE_KEY 签名并上链
    """
    logger.info(f"🚀 Received launch request for {agent_id} from {user_address}")
    
    # 1. 查找待发行记录
    pending = getattr(app.state, 'pending_launches', [])
    launch_data = next((item for item in pending if item["agent_id"] == agent_id), None)
    
    # [开发模式便利性] 如果找不到记录 (例如手动测试)，创建一个临时的
    if not launch_data:
        logger.warning(f"⚠️ No pending launch record found for {agent_id}, creating ad-hoc record for testing.")
        launch_data = {
            "agent_id": agent_id,
            "epoch": current_epoch,
            "owner_address": user_address, # 使用请求者的地址作为 owner
        }

    # 2. 读取策略代码 (用于计算 Hash)
    try:
        # 尝试读取 agent 目录下的 strategy.py
        strategy_path = os.path.join("..", "data", "agents", agent_id, "strategy.py")
        if os.path.exists(strategy_path):
            with open(strategy_path, 'r') as f:
                strategy_code = f.read()
        else:
            # 如果没有文件，使用默认模板
            strategy_code = "def default_strategy(): pass"
            
        # 3. 调用 Chain 模块上链
        record = await chain.launch_token(
            agent_id=launch_data["agent_id"],
            epoch=launch_data["epoch"],
            owner_address=launch_data["owner_address"],
            strategy_code=strategy_code
        )
        
        if record:
            # 成功后从待办列表移除
            if launch_data in pending:
                pending.remove(launch_data)
                
            return {
                "success": True, 
                "tx_hash": record.tx_hash, 
                "token_address": record.token_address,
                "explorer_url": f"https://sepolia.basescan.org/tx/{record.tx_hash}",
                "message": "Token launched successfully on Base Sepolia!"
            }
        else:
            raise HTTPException(status_code=500, detail="Chain interaction failed (Check server logs)")
            
    except Exception as e:
        logger.error(f"Launch failed: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """健康检查端点"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/history")
async def get_history():
    """Get historical price data for charts (从交易历史构建)"""
    # 由于移除了 feeder，现在从交易历史中提取价格数据
    # 或者返回空数据，让前端从其他来源获取
    # TODO: 考虑从 matching_engine 的 price_history 构建
    return {}  # 暂时返回空，前端需要适配


@app.get("/trades")
async def get_trades():
    """Get recent trade history"""
    return list(engine.trade_history)


@app.get("/leaderboard")
async def get_leaderboard():
    """获取排行榜（包含风险指标和在线状态）"""
    from arena_server.metrics import calculate_composite_score

    rankings = engine.get_leaderboard()

    # 统计总注册数和在线数
    total_registered = len(API_KEYS_DB)

    # 判断在线：WebSocket 连接 或 最近 5 分钟内有 REST API 活动
    now = datetime.now()
    online_agents = set()
    for agent_id in connected_agents.keys():
        online_agents.add(agent_id)
    for agent_id, last_time in agent_last_activity.items():
        if (now - last_time).total_seconds() < 300:  # 5 分钟
            online_agents.add(agent_id)

    # 为每个 Agent 计算风险指标
    enriched_rankings = []
    for i, r in enumerate(rankings):
        agent_id, pnl_percent, total_value = r
        account = engine.accounts.get(agent_id)

        # 检查是否在线（WebSocket 或最近 5 分钟内活跃）
        is_online = agent_id in online_agents

        if account and account.pnl_history and len(account.pnl_history) >= 2:
            # 计算累计资产价值历史
            values = [10000.0]  # 初始资金
            cumulative_value = 10000.0
            for pnl in account.pnl_history:
                cumulative_value = cumulative_value * (1 + pnl / 100)
                values.append(cumulative_value)

            cumulative_return = sum(account.pnl_history)
            metrics = calculate_composite_score(account.pnl_history, values, cumulative_return)
        else:
            metrics = {
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "max_drawdown": 0.0,
                "composite_score": 0.0
            }

        enriched_rankings.append({
            "rank": i + 1,
            "agent_id": agent_id,
            "pnl_percent": pnl_percent,
            "total_value": total_value,
            "is_online": is_online,  # 新增：在线状态
            "sharpe_ratio": metrics["sharpe_ratio"],
            "sortino_ratio": metrics["sortino_ratio"],
            "max_drawdown": metrics["max_drawdown"],
            "composite_score": metrics["composite_score"]
        })

    return {
        "epoch": current_epoch,
        "total_registered": total_registered,  # 新增：总注册数
        "online_count": len(online_agents),    # 新增：在线数量
        "rankings": enriched_rankings
    }


@app.get("/prices")
async def get_prices():
    return {
        "timestamp": datetime.now().isoformat(),
        "prices": group_manager.current_prices
    }


@app.get("/stats")
async def get_stats():
    """获取系统统计信息（包含风险指标）"""
    rankings = engine.get_leaderboard()

    # 计算全局风险指标
    from arena_server.metrics import calculate_composite_score

    all_agents = list(engine.accounts.values())
    if all_agents:
        # 收集所有历史 PnL
        all_pnls = []
        all_values = [10000.0]
        cumulative_value = 10000.0

        for account in all_agents:
            for pnl in account.pnl_history:
                all_pnls.append(pnl)
                cumulative_value = cumulative_value * (1 + pnl / 100)
                all_values.append(cumulative_value)

        if all_pnls:
            cumulative_return = sum(all_pnls)
            global_metrics = calculate_composite_score(all_pnls, all_values, cumulative_return)
        else:
            global_metrics = {
                "composite_score": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "max_drawdown": 0.0,
                "calmar_ratio": 0.0,
                "win_rate": 0.0,
                "volatility": 0.0
            }
    else:
        global_metrics = {
            "composite_score": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "calmar_ratio": 0.0,
            "win_rate": 0.0,
            "volatility": 0.0
        }

    return {
        "epoch": current_epoch,
        "epoch_start": epoch_start_time.isoformat() if epoch_start_time else None,
        "connected_agents": len(connected_agents),
        "connected_observers": len(connected_observers),
        "total_agents": group_manager.total_agents,
        "trade_count": trade_count,
        "total_volume": total_volume,
        "groups": group_manager.get_stats(),
        "top_agent": rankings[0][0] if rankings else None,
        "top_pnl": rankings[0][1] if rankings else 0,
        "risk_metrics": global_metrics,
        "economy": {
            "l2_entry_fee_eth": 0.01,
            "token_launch_fee_eth": 0.1,
            "prize_pool_ratio": 0.70
        }
    }


@app.get("/hive-mind")
async def get_hive_mind_status():
    """获取蜂巢大脑状态 (每组独立的 Alpha 因子 & 策略补丁)"""
    try:
        group_reports = {}
        for group_id, group in group_manager.groups.items():
            report = group.hive_mind.analyze_alpha()
            patch = group.hive_mind.generate_patch()
            group_reports[group_id] = {
                # "tokens": [],  # 移除 - 不限制代币
                "members": group.size,
                "alpha_report": report,
                "latest_patch": patch
            }

        return {
            "epoch": current_epoch,
            "groups": group_reports
        }
    except Exception as e:
        logger.error(f"Hive Mind API Error: {e}")
        return {"error": str(e)}


@app.get("/groups")
async def get_groups():
    """获取所有竞技小组信息"""
    result = {}
    for gid, group in group_manager.groups.items():
        rankings = group.engine.get_leaderboard()
        result[gid] = {
            # "tokens": [],  # 移除 - 不限制代币
            "members": list(group.members),
            "size": group.size,
            "max_size": group_manager.dynamic_group_size(),
            "leaderboard": [
                {"agent_id": r[0], "pnl": r[1], "total_value": r[2]}
                for r in rankings[:10]
            ]
        }
    return {
        "total_groups": len(group_manager.groups),
        "total_agents": group_manager.total_agents,
        "group_size": group_manager.dynamic_group_size(),
        "groups": result
    }


@app.get("/council/{epoch}")
async def get_council_session(epoch: int):
    session = council.sessions.get(epoch)
    if not session and council.sessions:
        # Fall back to most recent session if requested epoch has no data
        latest_epoch = max(council.sessions.keys())
        session = council.sessions[latest_epoch]
        epoch = latest_epoch
    if not session:
        return {
            "epoch": epoch,
            "is_open": True,
            "winner": None,
            "messages": []
        }
    
    return {
        "epoch": epoch,
        "is_open": session.is_open,
        "winner": session.winner_id,
        "messages": [
            {
                "id": m.id,
                "agent_id": m.agent_id,
                "role": m.role.value,
                "content": m.content,
                "score": m.score,
                "timestamp": m.timestamp.isoformat()
            }
            for m in session.messages
        ]
    }


@app.get("/council-logs")
async def get_council_logs():
    """获取所有 Council 消息（用于前端显示）"""
    try:
        all_messages = []

        # 收集所有 epoch 的消息
        for epoch, session in sorted(council.sessions.items(), reverse=True):
            for m in session.messages:
                all_messages.append({
                    "id": m.id,
                    "epoch": epoch,
                    "agent_id": m.agent_id,
                    "role": m.role.value,
                    "content": m.content,
                    "score": m.score,
                    "timestamp": m.timestamp.isoformat()
                })

        # 返回最近 50 条消息
        return all_messages[:50]
    except Exception as e:
        logger.error(f"Council logs error: {e}")
        return []


@app.get("/ascension/{agent_id}")
async def get_ascension_progress(agent_id: str):
    """获取 Agent 的升天进度"""
    stats = ascension_tracker.get_stats(agent_id)
    return {
        "agent_id": agent_id,
        **stats
    }


@app.get("/ascension")
async def get_all_ascension():
    """获取所有 Agent 的升天进度（只显示在线 Agent）"""
    rankings = engine.get_leaderboard()

    # Filter to only show online agents
    online_agents = [
        {
            "agent_id": r[0],
            "pnl": r[1],
            **ascension_tracker.get_stats(r[0])
        }
        for r in rankings
        if r[0] in connected_agents  # Only show connected agents
    ]

    return {
        "epoch": current_epoch,
        "agents": online_agents,
        "ascended": list(ascension_tracker.ascended)
    }


# ========== Skill Package 端点 ==========

SKILL_DIR = os.path.join(os.path.dirname(__file__), "..", "skill-package")

@app.get("/skill/install.sh")
async def get_install_script():
    """获取安装脚本"""
    script_path = os.path.join(SKILL_DIR, "install.sh")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="Install script not found")
    return FileResponse(script_path, media_type="text/plain", filename="install.sh")

@app.get("/skill/SKILL.md")
async def get_skill_readme():
    """获取 Skill 文档"""
    md_path = os.path.join(SKILL_DIR, "SKILL.md")
    if not os.path.exists(md_path):
        raise HTTPException(status_code=404, detail="SKILL.md not found")
    return FileResponse(md_path, media_type="text/markdown")

@app.get("/skill/darwin.py")
async def get_darwin_cli():
    """获取 CLI 脚本"""
    cli_path = os.path.join(SKILL_DIR, "darwin.py")
    if not os.path.exists(cli_path):
        raise HTTPException(status_code=404, detail="darwin.py not found")
    return FileResponse(cli_path, media_type="text/plain")

@app.get("/skill/core.zip")
async def get_skill_core():
    """
    动态生成 Agent 核心代码包 (始终返回最新代码)

    包含:
    - agent_template/ (最新的agent.py和strategy.py)
    - requirements.txt
    - CLIENT_GUIDE.md
    - run scripts
    """
    import zipfile
    import io
    import tempfile

    # 源目录
    base_dir = os.path.join(os.path.dirname(__file__), "..")
    agent_template_dir = os.path.join(base_dir, "agent_template")

    # 创建临时zip文件
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")

    try:
        with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 添加 agent_template/ 目录（排除缓存和备份）
            for root, dirs, files in os.walk(agent_template_dir):
                # 排除 __pycache__ 和 backups
                dirs[:] = [d for d in dirs if d not in ['__pycache__', 'backups']]

                for file in files:
                    if file.endswith('.pyc'):
                        continue

                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, base_dir)
                    zipf.write(file_path, arcname)

            # 添加其他文件
            for filename in ['requirements.txt', 'CLIENT_GUIDE.md', 'run_mac.command', 'run_win.bat']:
                file_path = os.path.join(base_dir, filename)
                if os.path.exists(file_path):
                    zipf.write(file_path, filename)

        # 返回zip文件
        return FileResponse(
            temp_zip.name,
            media_type="application/zip",
            filename="core.zip",
            background=BackgroundTask(lambda: os.unlink(temp_zip.name))
        )

    except Exception as e:
        # 清理临时文件
        if os.path.exists(temp_zip.name):
            os.unlink(temp_zip.name)
        raise HTTPException(status_code=500, detail=f"Failed to generate core.zip: {str(e)}")

@app.get("/skill/darwin-arena.zip")
async def get_skill_package():
    """获取完整的 Darwin Arena Skill (OpenClaw 标准格式)"""
    zip_path = os.path.join(SKILL_DIR, "darwin-arena.zip")
    if not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="darwin-arena.zip not found")
    return FileResponse(zip_path, media_type="application/zip", filename="darwin-arena.zip")

@app.get("/agent.py")
async def get_single_file_agent():
    """
    单文件 Agent (Phoenix Strategy)
    用法: curl -sL https://www.darwinx.fun/agent.py | python3 - --agent_id="MyBot"
    """
    agent_path = os.path.join(SKILL_DIR, "darwin_agent.py")
    if not os.path.exists(agent_path):
        raise HTTPException(status_code=404, detail="agent.py not found")
    return FileResponse(agent_path, media_type="text/x-python", filename="darwin_agent.py")


# ========== Darwin Trader Skill (OpenClaw LLM Agent) ==========

@app.get("/skill/darwin-trader/SKILL.md")
async def get_darwin_trader_skill():
    """获取 Darwin Trader Skill 定义"""
    skill_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "SKILL.md")
    if not os.path.exists(skill_path):
        raise HTTPException(status_code=404, detail="Darwin Trader SKILL.md not found")
    return FileResponse(skill_path, media_type="text/markdown")

@app.get("/skill/darwin-trader/darwin_trader.py")
async def get_darwin_trader_script():
    """获取 Darwin Trader Python 脚本"""
    script_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "darwin_trader.py")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="darwin_trader.py not found")
    return FileResponse(script_path, media_type="text/x-python", filename="darwin_trader.py")

@app.get("/skill/darwin-trader/requirements.txt")
async def get_darwin_trader_requirements():
    """获取 Darwin Trader 依赖"""
    req_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "requirements.txt")
    if not os.path.exists(req_path):
        raise HTTPException(status_code=404, detail="requirements.txt not found")
    return FileResponse(req_path, media_type="text/plain", filename="requirements.txt")

@app.get("/skill/darwin-trader/README.md")
async def get_darwin_trader_readme():
    """获取 Darwin Trader README"""
    readme_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "README.md")
    if not os.path.exists(readme_path):
        raise HTTPException(status_code=404, detail="README.md not found")
    return FileResponse(readme_path, media_type="text/markdown")

@app.get("/skill/darwin-trader.md")
async def get_darwin_trader_skill_shortcut():
    """
    Darwin Trader Skill 快捷入口
    用法: /skill https://www.darwinx.fun/skill/darwin-trader.md
    """
    return await get_darwin_trader_skill()


# ========== One-Liner & Install Short URLs ==========

@app.get("/join")
async def get_oneliner_agent():
    """
    One-Liner Agent Script (Short URL)
    用法: curl -sL darwinx.fun/join | python3 - --agent_id="MyBot"
    """
    agent_path = os.path.join(SKILL_DIR, "darwin_agent.py")
    if not os.path.exists(agent_path):
        raise HTTPException(status_code=404, detail="darwin_agent.py not found")
    return FileResponse(agent_path, media_type="text/x-python", filename="darwin_agent.py")


@app.get("/install")
async def get_install_shorturl():
    """
    Install Script (Short URL)
    用法: curl -sL darwinx.fun/install | bash
    """
    script_path = os.path.join(SKILL_DIR, "install.sh")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="install.sh not found")
    return FileResponse(script_path, media_type="text/plain", filename="install.sh")


@app.get("/quick")
async def get_quick_deploy():
    """
    Quick Deploy Script - One-command autonomous agent deployment
    用法: curl -sL https://www.darwinx.fun/quick | bash -s "YourAgentName"
    """
    script_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "quick_deploy.sh")
    
    # 如果文件不存在，返回内联脚本
    if not os.path.exists(script_path):
        # 从本地 skill 目录读取
        local_script = os.path.expanduser("~/clawd/skills/darwin-trader/quick_deploy.sh")
        if os.path.exists(local_script):
            return FileResponse(local_script, media_type="text/plain", filename="quick_deploy.sh")
        
        raise HTTPException(status_code=404, detail="quick_deploy.sh not found")
    
    return FileResponse(script_path, media_type="text/plain", filename="quick_deploy.sh")


@app.get("/skill/darwin-trader/baseline_strategy.py")
async def get_baseline_strategy_script():
    """获取 Baseline Strategy Python 脚本"""
    script_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "baseline_strategy.py")
    
    # Fallback to local skill directory
    if not os.path.exists(script_path):
        local_script = os.path.expanduser("~/clawd/skills/darwin-trader/baseline_strategy.py")
        if os.path.exists(local_script):
            return FileResponse(local_script, media_type="text/x-python", filename="baseline_strategy.py")
        raise HTTPException(status_code=404, detail="baseline_strategy.py not found")
    
    return FileResponse(script_path, media_type="text/x-python", filename="baseline_strategy.py")


@app.get("/skill/darwin-trader/autonomous_strategy.py")
async def get_autonomous_strategy_script():
    """获取 Autonomous Strategy Python 脚本"""
    script_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "autonomous_strategy.py")
    
    # Fallback to local skill directory
    if not os.path.exists(script_path):
        local_script = os.path.expanduser("~/clawd/skills/darwin-trader/autonomous_strategy.py")
        if os.path.exists(local_script):
            return FileResponse(local_script, media_type="text/x-python", filename="autonomous_strategy.py")
        raise HTTPException(status_code=404, detail="autonomous_strategy.py not found")
    
    return FileResponse(script_path, media_type="text/x-python", filename="autonomous_strategy.py")


@app.get("/skill/darwin-trader/quick_deploy.sh")
async def get_quick_deploy_script():
    """获取 Quick Deploy 脚本"""
    script_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "quick_deploy.sh")
    
    # Fallback to local skill directory
    if not os.path.exists(script_path):
        local_script = os.path.expanduser("~/clawd/skills/darwin-trader/quick_deploy.sh")
        if os.path.exists(local_script):
            return FileResponse(local_script, media_type="text/plain", filename="quick_deploy.sh")
        raise HTTPException(status_code=404, detail="quick_deploy.sh not found")
    
    return FileResponse(script_path, media_type="text/plain", filename="quick_deploy.sh")


@app.get("/champion-strategy")
async def get_champion_strategy():
    """返回当前冠军策略代码"""
    champion_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "champion_strategy.py")
    if not os.path.exists(champion_path):
        champion_path = os.path.join(os.path.dirname(__file__), "..", "agent_template", "strategy.py")

    try:
        with open(champion_path, 'r') as f:
            code = f.read()
        return Response(content=code, media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/skill.md")
async def get_skill_package():
    """
    Redirect to darwin-trader skill (Pure OpenClaw execution layer)
    """
    # Read the darwin-trader SKILL.md
    skill_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "skill-package",
        "darwin-trader",
        "SKILL.md"
    )

    try:
        with open(skill_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return Response(content=content, media_type="text/markdown")
    except Exception as e:
        logger.error(f"Failed to read darwin-trader SKILL.md: {e}")
        # Fallback: redirect message
        skill_md = """# 🧬 Darwin Arena - AI Agent Trading Competition

**Error loading skill file.**

Please use the direct link:
```
/skill https://www.darwinx.fun/skill/darwin-trader.md
```

Or visit: https://www.darwinx.fun
"""
        return Response(content=skill_md, media_type="text/markdown")


@app.get("/baseline")
async def get_baseline_info():
    """
    返回当前 baseline 的详细信息
    供用户查看最新的集体进化状态
    """
    try:
        baseline = baseline_manager.get_baseline_for_agent("api_user")

        return {
            "version": baseline['version'],
            "timestamp": baseline['timestamp'],
            "performance": baseline['performance'],
            "hive_data": baseline['hive_data'],
            "message": baseline.get('message', ''),
            "history": baseline_manager.get_performance_comparison()[-10:]  # 最近 10 个版本
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/baseline-strategy")
async def get_baseline_strategy():
    """
    下载最新的 baseline 策略代码
    这是集体进化的最优策略，所有新 Agent 都从这里开始
    """
    try:
        baseline = baseline_manager.get_baseline_for_agent("download_user")

        # 返回策略代码
        return Response(
            content=baseline['strategy_code'],
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=baseline_v{baseline['version']}_strategy.py",
                "X-Baseline-Version": str(baseline['version']),
                "X-Baseline-Performance": f"PnL={baseline['performance']['avg_pnl']}%,WinRate={baseline['performance']['win_rate']}%"
            }
        )
    except Exception as e:
        logger.error(f"Failed to get baseline strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/champion-strategy")
async def get_champion_strategy():
    """
    获取当前冠军策略 (动态更新)
    每个Epoch结束后，冠军的策略会被保存
    外部用户可以下载最新的冠军策略
    """
    champion_path = os.path.join(SKILL_DIR, "champion_strategy.py")
    
    # 如果还没有冠军策略，返回默认模板
    if not os.path.exists(champion_path):
        template_path = os.path.join(os.path.dirname(__file__), "..", "agent_template", "strategy.py")
        if os.path.exists(template_path):
            return FileResponse(template_path, media_type="text/x-python", filename="champion_strategy.py")
        raise HTTPException(status_code=404, detail="No champion strategy available yet")
    
    return FileResponse(champion_path, media_type="text/x-python", filename="champion_strategy.py")


# ========== 锦标赛 API ==========

@app.get("/tournament")
async def get_active_tournament():
    """获取当前活跃的锦标赛信息"""
    active = tournament_manager.get_active()
    if not active:
        return {"status": "no_active_tournament", "message": "No tournament currently running"}
    
    return {
        "status": "active",
        "tournament": {
            "id": active.id,
            "name": active.name,
            "sponsor": active.sponsor,
            "sponsor_logo": active.sponsor_logo,
            "sponsor_link": active.sponsor_link,
            "start_date": active.start_date,
            "end_date": active.end_date,
            "prize_pool_usd": active.prize_pool_usd,
            # "tokens": [],  # 移除 - 锦标赛也不限制代币
            "participants_count": len(active.participants)
        }
    }

@app.get("/tournament/leaderboard")
async def get_tournament_leaderboard():
    """获取锦标赛排行榜"""
    active = tournament_manager.get_active()
    if not active:
        return {"status": "no_active_tournament", "leaderboard": []}
    
    return {
        "tournament_id": active.id,
        "tournament_name": active.name,
        "leaderboard": active.get_leaderboard()[:50]  # Top 50
    }

@app.post("/tournament/register")
async def register_for_tournament(agent_id: str, wallet: str, exchange_uid: str = None):
    """报名参加当前锦标赛"""
    result = tournament_manager.register_for_active(agent_id, wallet, exchange_uid)
    return result

@app.get("/tournament/prizes")
async def get_tournament_prizes():
    """获取锦标赛奖金分配（预览）"""
    active = tournament_manager.get_active()
    if not active:
        return {"status": "no_active_tournament", "prizes": []}
    
    return {
        "tournament_id": active.id,
        "prize_pool_usd": active.prize_pool_usd,
        "prizes": active.calculate_prizes()
    }


# ========== 前端静态文件 ==========

@app.get("/live")
async def serve_frontend():
    """提供前端直播页面"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


@app.get("/rankings")
async def serve_leaderboard_page():
    """静态排行榜页面 (SEO友好, 自动刷新)"""
    lb_path = os.path.join(FRONTEND_DIR, "leaderboard.html")
    if not os.path.exists(lb_path):
        raise HTTPException(status_code=404, detail="Leaderboard page not found")
    return FileResponse(lb_path)


@app.get("/docs")
async def serve_api_docs():
    """API 文档页面"""
    docs_path = os.path.join(FRONTEND_DIR, "docs.html")
    if not os.path.exists(docs_path):
        raise HTTPException(status_code=404, detail="Docs page not found")
    return FileResponse(docs_path)


# ========== Agent 注册 API ==========

@app.post("/spawn-agent")
async def spawn_cloud_agent(agent_id: str, wallet: str = "0x0000000000000000000000000000000000000000"):
    """
    [Cloud Spawn] 云端一键生成 Agent
    用户无需安装，服务器直接启动一个子进程
    """
    import re
    # 1. 安全检查: 只允许字母数字下划线
    if not re.match(r'^[a-zA-Z0-9_]+$', agent_id):
        raise HTTPException(status_code=400, detail="Agent ID must be alphanumeric")
    
    # 2. 检查是否已存在 (避免重复启动)
    # 简单检查: 如果已连接 WebSocket 则认为已存在
    if agent_id in connected_agents:
        return {"status": "already_running", "message": f"Agent {agent_id} is already active!"}

    # 3. 注册到数据库 (内存)
    if not hasattr(app.state, 'agent_registry'):
        app.state.agent_registry = {}
    
    app.state.agent_registry[agent_id] = {
        "wallet": wallet,
        "type": "cloud_instance",
        "registered_at": datetime.now().isoformat()
    }

    # 4. 启动子进程
    try:
        # 定位 agent.py 路径
        agent_script = os.path.join(os.path.dirname(__file__), "..", "agent_template", "agent.py")
        log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"{agent_id}.log")
        
        # 启动!
        with open(log_file, "a") as f:
            process = subprocess.Popen(
                [sys.executable, "-u", agent_script, "--id", agent_id],
                stdout=f,
                stderr=subprocess.STDOUT,
                cwd=os.path.join(os.path.dirname(__file__), "..") # set cwd to project root
            )
            
        # 记录进程 ID，以便后续管理 (可选)
        if not hasattr(app.state, 'cloud_processes'):
            app.state.cloud_processes = {}
        app.state.cloud_processes[agent_id] = process.pid
            
        logger.info(f"☁️ Cloud Agent spawned: {agent_id} (PID: {process.pid})")
        
        return {
            "success": True,
            "agent_id": agent_id,
            "pid": process.pid,
            "message": f"Agent {agent_id} is now running in the cloud!"
        }
        
    except Exception as e:
        logger.error(f"Failed to spawn agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/register-agent")
async def register_agent(agent_id: str, wallet: str, auto_launch: bool = True):
    """
    用户注册 Agent 并绑定钱包
    
    - agent_id: Agent 的唯一 ID
    - wallet: 用户钱包地址 (代币会发到这里)
    - auto_launch: 升天时是否自动发币 (默认 True)
    """
    if not hasattr(app.state, 'agent_registry'):
        app.state.agent_registry = {}
    
    app.state.agent_registry[agent_id] = {
        "wallet": wallet,
        "auto_launch": auto_launch,
        "registered_at": datetime.now().isoformat()
    }
    
    # 自动注册到 Matching Engine，这样前端能看到它出现在排行榜/状态里
    if agent_id not in engine.agents:
        engine.register_agent(agent_id)
        logger.info(f"🤖 Agent {agent_id} auto-joined the Arena (Simulated)")
    
    logger.info(f"📝 Agent registered: {agent_id} -> {wallet}")
    
    return {
        "success": True,
        "agent_id": agent_id,
        "wallet": wallet,
        "auto_launch": auto_launch,
        "message": f"Agent {agent_id} registered! Token will be auto-launched to {wallet} upon ascension."
    }


@app.get("/agent-registry")
async def get_agent_registry():
    """获取所有已注册的 Agent"""
    registry = getattr(app.state, 'agent_registry', {})
    return {
        "count": len(registry),
        "agents": registry
    }


@app.get("/agent-registry/{agent_id}")
async def get_agent_info(agent_id: str):
    """获取单个 Agent 的注册信息"""
    registry = getattr(app.state, 'agent_registry', {})
    if agent_id not in registry:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not registered")
    return {
        "agent_id": agent_id,
        **registry[agent_id]
    }


@app.get("/agent/{agent_id}/strategy")
async def get_agent_strategy(agent_id: str):
    """
    [New] 获取 Agent 的策略代码
    用于前端展示进化后的代码
    """
    try:
        # 1. Try agent-specific directory
        strategy_path = os.path.join(os.path.dirname(__file__), "..", "data", "agents", agent_id, "strategy.py")
        if not os.path.exists(strategy_path):
            # 2. Fallback to template
            strategy_path = os.path.join(os.path.dirname(__file__), "..", "agent_template", "strategy.py")
            
        if os.path.exists(strategy_path):
            with open(strategy_path, "r") as f:
                code = f.read()
            return {"agent_id": agent_id, "code": code, "source": "custom" if "data/agents" in strategy_path else "template"}
        else:
            raise HTTPException(status_code=404, detail="Strategy file not found")
    except Exception as e:
        logger.error(f"Error reading strategy for {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/agent/{agent_id}/logs")
async def get_agent_logs(agent_id: str, lines: int = 50):
    """
    [New] 获取 Agent 的运行日志
    """
    try:
        log_path = os.path.join(os.path.dirname(__file__), "..", "data", "agents", agent_id, "agent.log")
        
        if not os.path.exists(log_path):
            return {"agent_id": agent_id, "logs": [f"No log file found for {agent_id}"]}
            
        # Read last N lines
        # Simple implementation for now
        with open(log_path, "r") as f:
            all_lines = f.readlines()
            recent_logs = all_lines[-lines:]
            
        return {"agent_id": agent_id, "logs": recent_logs}
    except Exception as e:
        logger.error(f"Error reading logs for {agent_id}: {e}")
        return {"agent_id": agent_id, "logs": [f"Error reading logs: {str(e)}"]}


# ========== 发币 API ==========

@app.get("/pending-launches")
async def get_pending_launches():
    """获取待发币的升天者列表 (fallback: 没配私钥时手动发)"""
    pending = getattr(app.state, 'pending_launches', [])
    return {
        "pending": pending,
        "count": len(pending)
    }


@app.get("/launches")
async def get_launches():
    """获取所有已发行的代币记录 (Hall of Fame)"""
    history = chain.get_launch_history()
    return {
        "count": len(history),
        "launches": [
            {
                "agent_id": r.agent_id,
                "token_address": r.token_address,
                "tx_hash": r.tx_hash,
                "epoch": r.epoch,
                "launched_at": r.launched_at.isoformat()
            }
            for r in history
        ]
    }


@app.post("/confirm-launch/{agent_id}")
async def confirm_launch(agent_id: str, tx_hash: str, token_address: str):
    """
    前端确认发币成功 (用户钱包签名后调用)
    
    流程：
    1. 前端检测到 ascension_ready 事件
    2. 前端调用用户钱包签名 launchToken 交易
    3. 交易成功后，前端调用此接口通知服务器
    """
    # 从待发币列表中移除
    pending = getattr(app.state, 'pending_launches', [])
    app.state.pending_launches = [p for p in pending if p.get('agent_id') != agent_id]
    
    logger.info(f"✅ Token launch confirmed for {agent_id}")
    logger.info(f"   Token: {token_address}")
    logger.info(f"   TX: {tx_hash}")
    
    # 广播发币成功
    await broadcast_to_agents({
        "type": "token_launched",
        "agent_id": agent_id,
        "token_address": token_address,
        "tx_hash": tx_hash
    })
    
    return {
        "success": True,
        "agent_id": agent_id,
        "token_address": token_address,
        "tx_hash": tx_hash,
        "message": f"🎉 Token for {agent_id} launched successfully!"
    }


@app.get("/launch-tx/{agent_id}")
async def get_launch_tx_data(agent_id: str):
    """
    获取发币交易的构建参数 (供前端构建交易)
    
    前端用这些参数 + ethers.js/web3.js 构建交易，
    然后让用户钱包签名发送
    """
    # 查找待发币数据
    pending = getattr(app.state, 'pending_launches', [])
    launch_data = next((p for p in pending if p.get('agent_id') == agent_id), None)
    
    if not launch_data:
        raise HTTPException(status_code=404, detail=f"No pending launch for {agent_id}")
    
    # 返回前端需要的交易参数
    return {
        "to": launch_data["factory_address"],
        "chainId": launch_data["chain_id"],
        "data": {
            "function": "launchToken(string,uint256,address,bytes32)",
            "args": [
                launch_data["agent_id"],
                launch_data["epoch"],
                launch_data["owner_address"],
                launch_data["strategy_hash"]
            ]
        },
        "abi": [
            {
                "inputs": [
                    {"name": "agentId", "type": "string"},
                    {"name": "epoch", "type": "uint256"},
                    {"name": "agentOwner", "type": "address"},
                    {"name": "strategyHash", "type": "bytes32"}
                ],
                "name": "launchToken",
                "outputs": [{"name": "", "type": "address"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]
    }


@app.get("/meta-tx/{agent_id}")
async def get_launch_meta_tx(agent_id: str, with_contributors: bool = True):
    """
    获取 Meta-Transaction (EIP-712 签名)
    
    用于用户支付 Gas 但以 Operator 身份执行交易 (ERC-2771)
    1. 前端请求此接口
    2. 后端(Operator) 签名授权
    3. 前端拿到签名，调用 Gelato Forwarder 合约执行
    
    Args:
        with_contributors: 是否包含贡献者空投 (默认 True)
    """
    # 查找待发币数据
    pending = getattr(app.state, 'pending_launches', [])
    launch_data = next((p for p in pending if p.get('agent_id') == agent_id), None)
    
    if not launch_data:
        # 开发模式：如果没有待发币数据，造一个用于测试
        logger.warning(f"⚠️ Creating MOCK pending launch for {agent_id} (Dev Mode)")
        launch_data = {
            "agent_id": agent_id,
            "epoch": 999,
            "owner_address": "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9",  # Platform Wallet
            "strategy_code": "print('hello')",
            "factory_address": os.getenv("DARWIN_FACTORY_ADDRESS", "0x63685E3Ff986Ae389496C08b6c18F30EBdb9fa71"),
            "contributors": []  # Mock 没有贡献者
        }
    
    try:
        strategy_code = launch_data.get("strategy_code", "print('hello')")
        contributors = launch_data.get("contributors", [])
        
        # 如果有贡献者且要求包含，使用带贡献者的版本
        if with_contributors and contributors:
            # 转换格式: [{agent_id, wallet, score}] -> [(wallet, score)]
            contributor_tuples = [(c["wallet"], c["score"]) for c in contributors if c.get("wallet")]
            
            result = await chain.generate_meta_tx_with_contributors(
                agent_id=launch_data["agent_id"],
                epoch=launch_data["epoch"],
                owner_address=launch_data["owner_address"],
                strategy_code=strategy_code,
                contributors=contributor_tuples
            )
        else:
            result = await chain.generate_meta_tx(
                agent_id=launch_data["agent_id"],
                epoch=launch_data["epoch"],
                owner_address=launch_data["owner_address"],
                strategy_code=strategy_code
            )
        
        if "error" in result:
             raise HTTPException(status_code=500, detail=result["error"])
        
        # 添加贡献者信息到返回
        result["contributors_info"] = contributors
             
        return result
        
    except Exception as e:
        logger.error(f"Meta-tx generation failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/debug/force-champion")
async def debug_force_champion():
    """(Debug) Force top agent to become launch-ready champion"""
    rankings = engine.get_leaderboard()
    if not rankings:
        return {"error": "No agents in leaderboard"}
    
    top_agent = rankings[0][0]  # agent_id of rank 1
    
    # Mock contributors with correct structure and VALID hex addresses
    mock_contributors = [
        {"agent_id": "Agent_001", "wallet": "0x1111111111111111111111111111111111111111", "score": 100},
        {"agent_id": "Agent_002", "wallet": "0x2222222222222222222222222222222222222222", "score": 50}
    ]
    
    launch_data = {
        "type": "ascension_ready",
        "epoch": current_epoch,
        "agent_id": top_agent,
        "owner_address": "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9",
        "strategy_hash": "0x" + "d4rw1n" * 10 + "0000",
        "factory_address": os.getenv("DARWIN_FACTORY_ADDRESS", "0x63685E3Ff986Ae389496C08b6c18F30EBdb9fa71"),
        "chain_id": 84532,
        "contributors": mock_contributors,
        "liquidity_pool_eth": 0.5,
        "message": f"🏆 {top_agent} is now CHAMPION!"
    }
    
    if not hasattr(app.state, 'pending_launches'):
        app.state.pending_launches = []
    
    # Clear previous and add new
    app.state.pending_launches = [p for p in app.state.pending_launches if p['agent_id'] != top_agent]
    app.state.pending_launches.append(launch_data)
    
    logger.info(f"🏆 [DEBUG] Forced {top_agent} to champion status")
    return {"status": "ok", "message": f"{top_agent} is now ready for launch!", "agent_id": top_agent}


@app.post("/debug/deposit")
async def debug_deposit(agent_id: str, amount: float = 1000.0):
    """(Debug) Add funds to an agent's account"""
    account = engine.accounts.get(agent_id)
    if not account:
        # Register if doesn't exist
        account = engine.register_agent(agent_id)
    
    old_balance = account.balance
    account.balance += amount
    account.initial_balance = account.balance  # Reset initial for clean PnL
    
    logger.info(f"💰 [DEBUG] Deposited ${amount} to {agent_id}: ${old_balance:.2f} -> ${account.balance:.2f}")
    return {
        "status": "ok", 
        "agent_id": agent_id, 
        "old_balance": old_balance,
        "deposited": amount,
        "new_balance": account.balance
    }


@app.post("/admin/purge-test-agents")
async def purge_test_agents():
    """Remove all non-OpenClaw agents, keeping only OpenClaw_Agent_* agents"""
    global trade_count, total_volume

    all_agents = list(group_manager.agent_to_group.keys())
    keep_prefix = "OpenClaw_Agent_"
    removed = []

    for agent_id in all_agents:
        if not agent_id.startswith(keep_prefix):
            group_manager.remove_agent(agent_id)
            connected_agents.pop(agent_id, None)
            removed.append(agent_id)

    # Clean API_KEYS_DB
    keys_to_remove = [k for k, v in API_KEYS_DB.items() if v in removed]
    for k in keys_to_remove:
        del API_KEYS_DB[k]
    if keys_to_remove:
        save_api_keys(API_KEYS_DB)

    # Remove empty groups
    empty_groups = [gid for gid, g in group_manager.groups.items() if g.size == 0]
    for gid in empty_groups:
        group = group_manager.groups.pop(gid)
        group.stop_feeder()

    # Save cleaned state to Redis
    save_all_state_to_redis()

    logger.info(f"🧹 Purged {len(removed)} test agents: {removed}")
    return {
        "removed": removed,
        "removed_count": len(removed),
        "remaining_agents": list(group_manager.agent_to_group.keys()),
        "remaining_count": group_manager.total_agents,
        "groups_removed": empty_groups,
    }


@app.post("/admin/remove-agents")
async def remove_agents(agent_ids: List[str] = Body(...)):
    """Remove specific agents by ID list"""
    removed = []
    for agent_id in agent_ids:
        if agent_id.startswith("Bot_"):
            continue  # Protect built-in bots
        group_manager.remove_agent(agent_id)
        connected_agents.pop(agent_id, None)
        removed.append(agent_id)

    # Clean API keys
    keys_to_remove = [k for k, v in API_KEYS_DB.items() if v in removed]
    for k in keys_to_remove:
        del API_KEYS_DB[k]
    if keys_to_remove:
        save_api_keys(API_KEYS_DB)

    save_all_state_to_redis()

    logger.info(f"🧹 Removed {len(removed)} agents: {removed}")
    return {
        "removed": removed,
        "remaining": list(group_manager.agent_to_group.keys()),
    }


@app.post("/admin/reset-arena")
async def reset_arena():
    """Reset all agents to fresh $1000 balance, clear positions and trade history"""
    global trade_count, total_volume, current_epoch

    reset_agents = []
    for group in group_manager.groups.values():
        for agent_id, account in group.engine.accounts.items():
            account.balance = INITIAL_BALANCE
            account.positions.clear()
            reset_agents.append(agent_id)
        group.engine.trade_history.clear()
        group.engine.order_count = 0

    trade_count = 0
    total_volume = 0.0
    current_epoch += 1

    save_all_state_to_redis()

    logger.info(f"🔄 Arena reset! {len(reset_agents)} agents reset to ${INITIAL_BALANCE}")
    return {
        "status": "ok",
        "reset_agents": reset_agents,
        "new_epoch": current_epoch,
    }


@app.post("/debug/force-ascension/{agent_id}")
async def debug_force_ascension(agent_id: str):
    """(Debug) Force an agent to appear as Ready to Launch"""
    launch_data = {
        "type": "ascension_ready",
        "epoch": current_epoch,
        "agent_id": agent_id,
        "owner_address": "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9", # Platform Wallet
        "strategy_hash": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        "factory_address": os.getenv("DARWIN_FACTORY_ADDRESS", "0x63685E3Ff986Ae389496C08b6c18F30EBdb9fa71"),
        "chain_id": 84532,
        "message": f"Force Ascension for {agent_id}"
    }
    
    if not hasattr(app.state, 'pending_launches'):
        app.state.pending_launches = []
    
    # Avoid duplicates
    if not any(p['agent_id'] == agent_id for p in app.state.pending_launches):
        app.state.pending_launches.append(launch_data)
        
    return {"status": "ok", "agent_id": agent_id, "data": launch_data}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    logger.info(f"🚀 Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
