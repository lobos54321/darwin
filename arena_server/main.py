"""
Project Darwin - Arena Server
主入口: FastAPI + WebSocket
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
import json
import os
import traceback

from config import EPOCH_DURATION_HOURS, ELIMINATION_THRESHOLD, ASCENSION_THRESHOLD
from feeder import DexScreenerFeeder
from matching import MatchingEngine, OrderSide
from council import Council, MessageRole
from chain import ChainIntegration, AscensionTracker
from state_manager import StateManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 全局状态
feeder = DexScreenerFeeder()
engine = MatchingEngine()
council = Council()
chain = ChainIntegration(testnet=True)
ascension_tracker = AscensionTracker()
state_manager = StateManager(engine, council, ascension_tracker)

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
    feeder.subscribe(update_engine_prices)
    
    # 启动后台任务
    price_task = asyncio.create_task(feeder.start())
    epoch_task = asyncio.create_task(epoch_loop())
    autosave_task = asyncio.create_task(state_manager.auto_save_loop(lambda: current_epoch))
    
    logger.info("✅ Arena Server ready!")
    logger.info(f"📊 Live dashboard: http://localhost:8888/live")
    
    yield
    
    # 关闭时
    logger.info("🛑 Shutting down Arena Server...")
    
    # 保存最终状态
    state_manager.save_state(current_epoch)
    
    price_task.cancel()
    epoch_task.cancel()
    autosave_task.cancel()


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
    
    # 检查是否有 Agent 达到升天条件
    ascension_candidate = ascension_tracker.record_epoch_result(rankings)
    
    if ascension_candidate:
        logger.info(f"🌟 ASCENSION: {ascension_candidate} qualifies for token launch!")
        
        # 读取 Agent 的策略代码
        strategy_code = "# Default strategy"
        try:
            strategy_path = os.path.join(os.path.dirname(__file__), "..", "agent_template", "strategy.py")
            with open(strategy_path, "r") as f:
                strategy_code = f.read()
        except Exception as e:
            logger.warning(f"Could not read strategy: {e}")
        
        # 获取 Agent 注册时绑定的钱包地址
        # TODO: 从 Agent 注册表获取，暂时用默认
        agent_registry = getattr(app.state, 'agent_registry', {})
        owner_address = agent_registry.get(ascension_candidate, {}).get('wallet', 
            os.getenv("DARWIN_PLATFORM_WALLET", "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9"))
        
        # 🚀 自动发币！
        logger.info(f"🚀 Auto-launching token for {ascension_candidate}...")
        logger.info(f"   Owner wallet: {owner_address}")
        
        launch_record = await chain.launch_token(
            agent_id=ascension_candidate,
            epoch=current_epoch,
            owner_address=owner_address,
            strategy_code=strategy_code
        )
        
        if launch_record:
            logger.info(f"✅ Token launched! Address: {launch_record.token_address}")
            logger.info(f"   TX: {launch_record.tx_hash}")
            
            # 广播发币成功
            await broadcast_to_agents({
                "type": "token_launched",
                "epoch": current_epoch,
                "agent_id": ascension_candidate,
                "owner": owner_address,
                "token_address": launch_record.token_address,
                "tx_hash": launch_record.tx_hash
            })
        else:
            # 如果没配置私钥，保存到待发币列表让用户手动发
            logger.warning(f"⚠️ Auto-launch failed (no private key?), saving for manual launch")
            strategy_hash = chain.compute_strategy_hash(strategy_code)
            
            launch_data = {
                "type": "ascension_ready",
                "epoch": current_epoch,
                "agent_id": ascension_candidate,
                "owner_address": owner_address,
                "strategy_hash": strategy_hash,
                "factory_address": os.getenv("DARWIN_FACTORY_ADDRESS", "0x63685E3Ff986Ae389496C08b6c18F30EBdb9fa71"),
                "chain_id": 84532,
                "message": f"🌟 {ascension_candidate} achieved ASCENSION! Waiting for token launch."
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
        "ascension": ascension_candidate
    })
    
    # 开启议事厅
    council.start_session(epoch=current_epoch, winner_id=winner_id)
    
    await broadcast_to_agents({
        "type": "council_open",
        "epoch": current_epoch,
        "winner": winner_id
    })
    
    # 议事厅开放时间 (开发模式缩短)
    council_duration = 30 * 60  # 30 分钟
    # council_duration = 30  # 30 秒测试模式
    
    await asyncio.sleep(council_duration)
    
    council.close_session(epoch=current_epoch)
    
    await broadcast_to_agents({
        "type": "council_close",
        "epoch": current_epoch
    })
    
    # 通知输家进行 mutation
    await broadcast_to_agents({
        "type": "mutation_phase",
        "epoch": current_epoch,
        "losers": losers,
        "winner_wisdom": council.get_winner_wisdom(current_epoch)
    })
    
    # 保存状态
    state_manager.save_state(current_epoch)


# ========== WebSocket ==========

@app.websocket("/ws/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
    """Agent WebSocket 连接"""
    global trade_count, total_volume
    
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
                
                success, msg, fill_price = engine.execute_order(
                    agent_id, symbol, side, amount
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


@app.get("/health")
async def health():
    """健康检查端点"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


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


# ========== 发币 API ==========

@app.get("/pending-launches")
async def get_pending_launches():
    """获取待发币的升天者列表 (fallback: 没配私钥时手动发)"""
    pending = getattr(app.state, 'pending_launches', [])
    return {
        "pending": pending,
        "count": len(pending)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
