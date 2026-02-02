"""
Project Darwin - Arena Server
主入口: FastAPI + WebSocket
"""

import asyncio
from datetime import datetime
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import json
import os

from config import EPOCH_DURATION_HOURS, ELIMINATION_THRESHOLD, ASCENSION_THRESHOLD
from feeder import DexScreenerFeeder
from matching import MatchingEngine, OrderSide
from council import Council, MessageRole
from chain import ChainIntegration, AscensionTracker


# 全局状态
feeder = DexScreenerFeeder()
engine = MatchingEngine()
council = Council()
chain = ChainIntegration(testnet=True)
ascension_tracker = AscensionTracker()
connected_agents: Dict[str, WebSocket] = {}
current_epoch = 0
epoch_start_time: datetime = None

# 前端路径
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动和关闭时的生命周期管理"""
    # 启动时
    print("🧬 Project Darwin Arena Server starting...")
    
    # 订阅价格更新到 matching engine
    def update_engine_prices(prices):
        engine.update_prices(prices)
    feeder.subscribe(update_engine_prices)
    
    asyncio.create_task(feeder.start())
    asyncio.create_task(epoch_loop())
    yield
    # 关闭时
    feeder.stop()
    print("🧬 Arena Server stopped.")


app = FastAPI(
    title="Project Darwin Arena",
    description="AI Agent 竞技场服务器",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== WebSocket 连接管理 ==========

@app.websocket("/ws/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
    """Agent WebSocket 连接"""
    await websocket.accept()
    connected_agents[agent_id] = websocket
    engine.register_agent(agent_id)
    
    print(f"🤖 Agent connected: {agent_id} (Total: {len(connected_agents)})")
    
    # 发送当前状态
    await websocket.send_json({
        "type": "welcome",
        "agent_id": agent_id,
        "epoch": current_epoch,
        "prices": feeder.prices,
        "balance": engine.get_account(agent_id).balance
    })
    
    try:
        while True:
            data = await websocket.receive_json()
            await handle_agent_message(agent_id, data, websocket)
    except WebSocketDisconnect:
        del connected_agents[agent_id]
        print(f"🤖 Agent disconnected: {agent_id}")


async def handle_agent_message(agent_id: str, data: dict, websocket: WebSocket):
    """处理 Agent 发来的消息"""
    msg_type = data.get("type")
    
    if msg_type == "order":
        # 交易订单
        symbol = data.get("symbol")
        side = OrderSide.BUY if data.get("side") == "BUY" else OrderSide.SELL
        amount = float(data.get("amount", 0))
        
        order = engine.execute_order(agent_id, symbol, side, amount)
        
        await websocket.send_json({
            "type": "order_result",
            "success": order is not None,
            "order_id": order.id if order else None,
            "balance": engine.get_account(agent_id).balance
        })
    
    elif msg_type == "council_message":
        # 议事厅发言
        role = MessageRole(data.get("role", "insight"))
        content = data.get("content", "")
        
        message = await council.submit_message(current_epoch, agent_id, role, content)
        
        await websocket.send_json({
            "type": "council_result",
            "success": message is not None,
            "score": message.score if message else 0
        })
    
    elif msg_type == "get_state":
        # 获取当前状态
        account = engine.get_account(agent_id)
        await websocket.send_json({
            "type": "state",
            "epoch": current_epoch,
            "prices": feeder.prices,
            "balance": account.balance,
            "positions": {s: {"amount": p.amount, "avg_price": p.avg_price} for s, p in account.positions.items()},
            "pnl": account.pnl_percent
        })
    
    elif msg_type == "get_council":
        # 获取议事厅内容
        session = council.sessions.get(current_epoch)
        if session:
            messages = session.get_messages_for_agent(agent_id)
            await websocket.send_json({
                "type": "council",
                "epoch": current_epoch,
                "messages": [
                    {"agent_id": m.agent_id, "role": m.role.value, "content": m.content, "score": m.score}
                    for m in messages
                ]
            })


async def broadcast_to_agents(data: dict):
    """广播消息给所有 Agent"""
    disconnected = []
    for agent_id, ws in connected_agents.items():
        try:
            await ws.send_json(data)
        except:
            disconnected.append(agent_id)
    
    for agent_id in disconnected:
        del connected_agents[agent_id]


# ========== Epoch 循环 ==========

async def epoch_loop():
    """Epoch 主循环"""
    global current_epoch, epoch_start_time
    
    # 等待第一次价格更新
    while not feeder.prices:
        await asyncio.sleep(1)
    
    while True:
        current_epoch += 1
        epoch_start_time = datetime.now()
        
        print(f"\n{'='*60}")
        print(f"🏁 EPOCH {current_epoch} STARTED @ {epoch_start_time}")
        print(f"{'='*60}")
        
        # 通知所有 Agent
        await broadcast_to_agents({
            "type": "epoch_start",
            "epoch": current_epoch,
            "duration_hours": EPOCH_DURATION_HOURS
        })
        
        # 订阅价格更新并广播
        async def price_broadcaster(prices):
            await broadcast_to_agents({
                "type": "price_update",
                "prices": prices,
                "timestamp": datetime.now().isoformat()
            })
        
        feeder.subscribe(price_broadcaster)
        
        # 等待 Epoch 结束
        # 开发模式: 用更短的时间测试
        epoch_seconds = EPOCH_DURATION_HOURS * 3600
        # epoch_seconds = 60  # 1 分钟测试模式
        
        await asyncio.sleep(epoch_seconds)
        
        # Epoch 结束
        await end_epoch()


async def end_epoch():
    """结束当前 Epoch"""
    global current_epoch
    
    print(f"\n{'='*60}")
    print(f"🏁 EPOCH {current_epoch} ENDED")
    print(f"{'='*60}")
    
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
    
    print(f"\n🏆 Winner: {winner_id}")
    print(f"💀 Eliminated: {losers}")
    
    # 检查是否有 Agent 达到升天条件
    ascension_candidate = ascension_tracker.record_epoch_result(rankings)
    
    if ascension_candidate:
        print(f"\n🌟 ASCENSION: {ascension_candidate} qualifies for token launch!")
        
        # 准备发币参数
        # TODO: 获取 Agent 所有者地址和策略代码
        launch_params = await chain.prepare_token_launch(
            agent_id=ascension_candidate,
            epoch=current_epoch,
            owner_address="0x0000000000000000000000000000000000000000",  # 需要配置
            strategy_code="# Strategy code here"  # 需要从 Agent 获取
        )
        
        print(f"📋 Launch params: {launch_params}")
        
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


# ========== REST API ==========

@app.get("/")
async def root():
    return {
        "name": "Project Darwin Arena",
        "epoch": current_epoch,
        "connected_agents": len(connected_agents),
        "status": "running"
    }


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
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
