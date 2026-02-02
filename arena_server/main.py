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
        
        # 准备发币参数
        launch_params = await chain.prepare_token_launch(
            agent_id=ascension_candidate,
            epoch=current_epoch,
            owner_address="0x0000000000000000000000000000000000000000",
            strategy_code="# Strategy code here"
        )
        
        logger.info(f"📋 Launch params: {launch_params}")
        
        # 通知升天
        await broadcast_to_agents({
            "type": "ascension",
            "epoch": current_epoch,
            "agent_id": ascension_candidate,
            "launch_params": launch_params
        })
    
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
