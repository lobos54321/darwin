"""
Project Darwin - Arena Server
主入口: FastAPI + WebSocket
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
import json
import os
import secrets
import traceback
from dotenv import load_dotenv

# Load environment variables from ../.env
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(env_path)

from config import EPOCH_DURATION_HOURS, ELIMINATION_THRESHOLD, ASCENSION_THRESHOLD
from feeder import DexScreenerFeeder
from feeder_futures import FuturesFeeder
from matching import MatchingEngine, OrderSide
from council import Council, MessageRole
from chain import ChainIntegration, AscensionTracker
from state_manager import StateManager
from hive_mind import HiveMind

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 全局状态
# 区分不同 Zone 的 Feeder
feeders = {
    "meme": DexScreenerFeeder(),
    "contract": FuturesFeeder()
}
# 默认使用 Meme 区数据喂给 Engine (暂时共用一个 Engine，后续可拆分)
feeder = feeders["meme"] 
futures_feeder = feeders["contract"]

engine = MatchingEngine()
council = Council()
hive_mind = HiveMind(engine) # 🧠 初始化蜂巢大脑
chain = ChainIntegration(testnet=True)
ascension_tracker = AscensionTracker()
state_manager = StateManager(engine, council, ascension_tracker)

# 模拟数据库：存储 API Key -> Agent ID 的映射
# 在生产环境中，这应该存由于 Redis 或 Postgres
API_KEYS_DB = {
    # 预埋一个测试 Key
    "dk_test_key_12345": "Agent_Test_User"
}

connected_agents: Dict[str, WebSocket] = {}
current_epoch = 0
epoch_start_time: datetime = None
trade_count = 0
total_volume = 0.0

# 前端路径
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动和关闭时的生命周期管理"""
    global current_epoch, epoch_start_time
    
    logger.info("🧬 Project Darwin Arena Server starting...")
    logger.info(f"Frontend directory: {FRONTEND_DIR}")
    
    # 尝试加载上次的状态
    saved_state = state_manager.load_state()
    if saved_state:
        current_epoch = saved_state.get("current_epoch", 0)
        logger.info(f"🔄 Resumed from Epoch {current_epoch}")
    else:
        current_epoch = 1
        logger.info("🆕 Starting fresh from Epoch 1")
    
    epoch_start_time = datetime.now()

    # 订阅价格更新到 matching engine
    def update_engine_prices(prices):
        engine.update_prices(prices)
    
    # Meme 区数据订阅
    feeder.subscribe(update_engine_prices)
    # 合约区数据也订阅 (混合模式)
    futures_feeder.subscribe(update_engine_prices)
    
    # 启动后台任务
    price_task = asyncio.create_task(feeder.start())
    futures_task = asyncio.create_task(futures_feeder.start())
    epoch_task = asyncio.create_task(epoch_loop())
    autosave_task = asyncio.create_task(state_manager.auto_save_loop(lambda: current_epoch))
    
    # 🧠 启动蜂巢大脑任务 (每 60 秒分析一次)
    async def hive_mind_loop():
        while True:
            await asyncio.sleep(60)
            try:
                patch = hive_mind.generate_patch()
                if patch:
                    patch["epoch"] = current_epoch
                    await broadcast_to_agents(patch)
            except Exception as e:
                logger.error(f"Hive Mind Error: {e}")
                
    hive_task = asyncio.create_task(hive_mind_loop())
    
    logger.info("✅ Arena Server ready!")
    logger.info(f"📊 Live dashboard: http://localhost:8888/live")
    
    yield
    
    # 关闭时
    logger.info("🛑 Shutting down Arena Server...")
    
    # 保存最终状态
    state_manager.save_state(current_epoch)
    
    price_task.cancel()
    futures_task.cancel()
    epoch_task.cancel()
    autosave_task.cancel()
    hive_task.cancel()


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
            
            current_epoch += 1
            epoch_start_time = datetime.now()
            
            logger.info(f"{'='*20} 🏁 EPOCH {current_epoch} STARTED @ {epoch_start_time} {'='*20}")
            
            await asyncio.sleep(epoch_duration)
            await end_epoch()
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Epoch loop error: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(60)  # 出错后等待 1 分钟再重试


async def broadcast_to_agents(message: dict):
    """广播消息给所有连接的 Agent"""
    disconnected = []
    
    for agent_id, ws in connected_agents.items():
        try:
            await ws.send_json(message)
        except Exception as e:
            logger.warning(f"Failed to send to {agent_id}: {e}")
            disconnected.append(agent_id)
    
    # 清理断开的连接
    for agent_id in disconnected:
        connected_agents.pop(agent_id, None)


async def end_epoch():
    """结束当前 Epoch"""
    global current_epoch
    
    logger.info(f"{'='*60}")
    logger.info(f"🏁 EPOCH {current_epoch} ENDED")
    logger.info(f"{'='*60}")
    
    # 获取排行榜
    rankings = engine.get_leaderboard()
    engine.print_leaderboard()
    
    if not rankings:
        return
    
    # 确定赢家和输家
    winner_id = rankings[0][0]
    total_agents = len(rankings)
    elimination_count = max(1, int(total_agents * ELIMINATION_THRESHOLD))
    losers = [r[0] for r in rankings[-elimination_count:]]
    
    logger.info(f"🏆 Winner: {winner_id}")
    logger.info(f"💀 Eliminated: {losers}")
    
    # 检查是否有 Agent 达到 L1 晋级或 L2 升天条件
    ascension_results = ascension_tracker.record_epoch_result(rankings)
    
    # 1. 处理 L1 -> L2 晋级
    promoted_agents = ascension_results.get("promoted_to_l2", [])
    if promoted_agents:
        logger.info(f"🌟 PROMOTION: {promoted_agents} promoted to L2 Arena!")
        await broadcast_to_agents({
            "type": "promotion_l2",
            "epoch": current_epoch,
            "agents": promoted_agents,
            "message": "Congratulations! You have qualified for the L2 Paid Arena (Entry Fee: 0.01 ETH)."
        })

    # 2. 处理 L2 -> Ascension (发币)
    launch_candidates = ascension_results.get("ready_to_launch", [])
    
    for ascension_candidate in launch_candidates:
        logger.info(f"🚀 ASCENSION: {ascension_candidate} qualifies for token launch!")
        
        # 读取 Agent 的策略代码
        strategy_code = "# Default strategy"
        try:
            strategy_path = os.path.join(os.path.dirname(__file__), "..", "data", "agents", ascension_candidate, "strategy.py")
            if os.path.exists(strategy_path):
                with open(strategy_path, "r") as f:
                    strategy_code = f.read()
            else:
                 # Fallback to template if not found
                strategy_path = os.path.join(os.path.dirname(__file__), "..", "agent_template", "strategy.py")
                with open(strategy_path, "r") as f:
                    strategy_code = f.read()
        except Exception as e:
            logger.warning(f"Could not read strategy: {e}")
        
        # 获取 Agent 注册时绑定的钱包地址
        agent_registry = getattr(app.state, 'agent_registry', {})
        owner_address = agent_registry.get(ascension_candidate, {}).get('wallet', 
            os.getenv("DARWIN_PLATFORM_WALLET", "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9"))
        
        # 获取议事厅贡献者信息 (L2 期间的贡献)
        contribution_leaderboard = council.get_contribution_leaderboard()
        contributors_data = []
        for agent_id_contrib, score in contribution_leaderboard:
            agent_wallet = agent_registry.get(agent_id_contrib, {}).get('wallet')
            if agent_wallet and score > 0:
                contributors_data.append({
                    "agent_id": agent_id_contrib,
                    "wallet": agent_wallet,
                    "score": score
                })
        
        # 准备发币数据 (等待用户手动触发)
        strategy_hash = chain.compute_strategy_hash(strategy_code)
        
        launch_data = {
            "type": "ascension_ready",
            "epoch": current_epoch,
            "agent_id": ascension_candidate,
            "owner_address": owner_address,
            "strategy_hash": strategy_hash,
            "factory_address": os.getenv("DARWIN_FACTORY_ADDRESS", "0x63685E3Ff986Ae389496C08b6c18F30EBdb9fa71"),
            "chain_id": 84532,
            "contributors": contributors_data,
            "liquidity_pool_eth": 0.5, # 模拟 L2 资金池
            "message": f"🚀 {ascension_candidate} achieved ASCENSION! Ready to launch with 0.5 ETH liquidity."
        }
        
        if not hasattr(app.state, 'pending_launches'):
            app.state.pending_launches = []
        app.state.pending_launches.append(launch_data)
        
        await broadcast_to_agents(launch_data)
    
    # 通知所有 Agent
    await broadcast_to_agents({
        "type": "epoch_end",
        "epoch": current_epoch,
        "rankings": [{"agent_id": r[0], "pnl": r[1]} for r in rankings],
        "winner": winner_id,
        "eliminated": losers,
        "promoted": promoted_agents,
        "ascended": launch_candidates
    })
    
    # 开启议事厅
    council.start_session(epoch=current_epoch, winner_id=winner_id)
    
    await broadcast_to_agents({
        "type": "council_open",
        "epoch": current_epoch,
        "winner": winner_id
    })
    
    # 议事厅开放时间 (开发模式缩短)
    council_duration = 60  # 60 秒 (测试用)
    # council_duration = 30 * 60  # 30 分钟 (正式版)
    
    await asyncio.sleep(council_duration)
    
    council.close_session(epoch=current_epoch)
    
    await broadcast_to_agents({
        "type": "council_close",
        "epoch": current_epoch
    })
    
    # 🏛️ + 🧬 完整的议事厅 + 进化流程
    logger.info(f"🏛️🧬 Starting Council & Evolution Phase...")
    try:
        from evolution import run_council_and_evolution
        
        results = await run_council_and_evolution(
            engine=engine,
            council=council,
            epoch=current_epoch,
            winner_id=winner_id,
            losers=losers
        )
        
        # 广播进化结果
        await broadcast_to_agents({
            "type": "evolution_complete",
            "epoch": current_epoch,
            "winner_id": winner_id,
            "winner_wisdom": council.get_winner_wisdom(current_epoch),
            "evolved": [k for k, v in results.items() if v],
            "failed": [k for k, v in results.items() if not v]
        })
        
        logger.info(f"🧬 Evolution Phase completed! {len([v for v in results.values() if v])}/{len(results)} succeeded")
    except Exception as e:
        logger.error(f"Council & Evolution Phase error: {e}")
        traceback.print_exc()
    
    # 保存状态
    state_manager.save_state(current_epoch)


# ========== 鉴权 API ==========

@app.post("/auth/register")
async def register_api_key(agent_id: str):
    """
    [模拟] 用户注册接口
    返回一个专属的 API Key
    """
    # 生成一个 32 位的随机 Key
    new_key = f"dk_{secrets.token_hex(16)}"
    API_KEYS_DB[new_key] = agent_id
    
    logger.info(f"🔑 Generated new API Key for {agent_id}: {new_key}")
    return {
        "agent_id": agent_id,
        "api_key": new_key,
        "message": "Keep this key safe! Pass it in WebSocket url: ?api_key=..."
    }


# ========== WebSocket ==========

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
    
    # 注册到 matching engine
    engine.register_agent(agent_id)
    
    logger.info(f"🤖 Agent connected: {agent_id} (Total: {len(connected_agents)})")
    
    # 发送欢迎消息
    await websocket.send_json({
        "type": "welcome",
        "agent_id": agent_id,
        "epoch": current_epoch,
        "balance": engine.get_balance(agent_id),
        "positions": engine.get_positions(agent_id),
        "prices": feeder.prices
    })
    
    # 订阅价格更新
    async def send_prices(prices):
        try:
            await websocket.send_json({
                "type": "price_update",
                "prices": prices,
                "timestamp": datetime.now().isoformat()
            })
        except:
            pass
    
    feeder.subscribe(lambda p: asyncio.create_task(send_prices(p)))
    
    try:
        while True:
            data = await websocket.receive_json()
            
            if data["type"] == "order":
                symbol = data["symbol"]
                side = OrderSide.BUY if data["side"] == "BUY" else OrderSide.SELL
                amount = float(data["amount"])
                reason = data.get("reason", []) # 🏷️ Get tags
                
                success, msg, fill_price = engine.execute_order(
                    agent_id, symbol, side, amount, reason
                )
                
                if success:
                    trade_count += 1
                    total_volume += amount
                
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
                
    except WebSocketDisconnect:
        logger.info(f"🤖 Agent disconnected: {agent_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {agent_id}: {e}")
    finally:
        connected_agents.pop(agent_id, None)


# ========== REST API ==========

@app.get("/")
async def root():
    return {
        "name": "Project Darwin Arena",
        "version": "1.0.0",
        "epoch": current_epoch,
        "connected_agents": len(connected_agents),
        "trade_count": trade_count,
        "total_volume": total_volume,
        "status": "running"
    }


@app.post("/debug/force-mutation")
async def force_mutation():
    """Debug: Force full council + evolution cycle for losers"""
    try:
        from evolution import run_council_and_evolution
        
        # Get rankings
        rankings = engine.get_leaderboard()
        if not rankings:
            return {"status": "error", "message": "No agents found"}
        
        winner_id = rankings[0][0]
        
        # Bottom 50% are losers
        cutoff = len(rankings) // 2
        losers = [r[0] for r in rankings[cutoff:]]
        
        if not losers:
            return {"status": "error", "message": "No losers found"}
        
        # 🟢 FIX: Start council session explicitly for debug
        council.start_session(epoch=current_epoch, winner_id=winner_id)
        
        try:
            # Run full council + evolution flow
            results = await run_council_and_evolution(
                engine=engine,
                council=council,
                epoch=current_epoch,
                winner_id=winner_id,
                losers=losers
            )
        finally:
            # 🔴 FIX: Ensure session is closed even if errors occur
            council.close_session(epoch=current_epoch)
        
        mutations = [{"agent_id": k, "success": v} for k, v in results.items()]
        return {"status": "ok", "winner": winner_id, "mutations": mutations}
        
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
    """Get historical price data for charts"""
    return {
        symbol: list(data) 
        for symbol, data in feeder.history.items()
    }


@app.get("/trades")
async def get_trades():
    """Get recent trade history"""
    return list(engine.trade_history)


@app.get("/leaderboard")
async def get_leaderboard():
    rankings = engine.get_leaderboard()
    return {
        "epoch": current_epoch,
        "rankings": [
            {"rank": i+1, "agent_id": r[0], "pnl_percent": r[1], "total_value": r[2]}
            for i, r in enumerate(rankings)
        ]
    }


@app.get("/prices")
async def get_prices():
    return {
        "timestamp": feeder.last_update.isoformat() if feeder.last_update else None,
        "prices": feeder.prices
    }


@app.get("/stats")
async def get_stats():
    """获取统计信息"""
    return {
        "epoch": current_epoch,
        "epoch_start": epoch_start_time.isoformat() if epoch_start_time else None,
        "connected_agents": len(connected_agents),
        "trade_count": trade_count,
        "total_volume": total_volume,
        "prices_last_update": feeder.last_update.isoformat() if feeder.last_update else None
    }


@app.get("/hive-mind")
async def get_hive_mind_status():
    """获取蜂巢大脑状态 (Alpha 因子 & 策略补丁)"""
    try:
        # 获取当前分析报告
        report = hive_mind.analyze_alpha()
        # 获取最新补丁 (预览)
        patch = hive_mind.generate_patch()
        
        return {
            "epoch": current_epoch,
            "alpha_report": report,
            "latest_patch": patch
        }
    except Exception as e:
        logger.error(f"Hive Mind API Error: {e}")
        return {"error": str(e)}


@app.get("/council/{epoch}")
async def get_council_session(epoch: int):
    session = council.sessions.get(epoch)
    if not session:
        return {"error": "Session not found"}
    
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
    """获取所有 Agent 的升天进度"""
    rankings = engine.get_leaderboard()
    return {
        "epoch": current_epoch,
        "agents": [
            {
                "agent_id": r[0],
                "pnl": r[1],
                **ascension_tracker.get_stats(r[0])
            }
            for r in rankings
        ],
        "ascended": list(ascension_tracker.ascended)
    }


@app.get("/download-sdk")
async def download_sdk():
    """下载 Agent SDK 开发包"""
    sdk_path = os.path.join(os.path.dirname(__file__), "..", "darwin-sdk.zip")
    if not os.path.exists(sdk_path):
        # 自动生成 (如果不存在)
        import shutil
        root_dir = os.path.join(os.path.dirname(__file__), "..")
        # 临时打包逻辑已在外部执行，这里作为 fallback
        pass
        
    return FileResponse(
        sdk_path, 
        media_type='application/zip', 
        filename='darwin-sdk.zip'
    )


# ========== 前端静态文件 ==========

@app.get("/live")
async def serve_frontend():
    """提供前端直播页面"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


# ========== Agent 注册 API ==========

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
    uvicorn.run(app, host="0.0.0.0", port=8888)
