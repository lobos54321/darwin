#!/usr/bin/env python3
"""
多 Agent 并行运行测试
模拟真实的 Arena 场景：多个 Agent 同时交易、竞争
"""

import asyncio
import subprocess
import signal
import sys
import json
import random
from datetime import datetime
import aiohttp

ARENA_URL = "ws://localhost:8888"
REST_URL = "http://localhost:8888"
NUM_AGENTS = 10


class SimulatedAgent:
    """模拟 Agent"""
    
    def __init__(self, agent_id: str, strategy_type: str = "random"):
        self.agent_id = agent_id
        self.strategy_type = strategy_type
        self.balance = 1000.0
        self.positions = {}
        self.trades = 0
        self.pnl = 0.0
    
    def decide(self, prices: dict) -> dict:
        """根据策略类型做决策"""
        
        if self.strategy_type == "random":
            # 随机策略
            if random.random() < 0.3:  # 30% 概率交易
                symbol = random.choice(list(prices.keys()))
                side = random.choice(["BUY", "SELL"])
                amount = random.uniform(50, 200)
                return {"symbol": symbol, "side": side, "amount": amount}
        
        elif self.strategy_type == "momentum":
            # 动量策略: 涨就买
            for symbol, info in prices.items():
                change = info.get("priceChange24h", 0)
                if change > 5 and symbol not in self.positions:
                    return {"symbol": symbol, "side": "BUY", "amount": 150}
        
        elif self.strategy_type == "contrarian":
            # 逆势策略: 跌就买
            for symbol, info in prices.items():
                change = info.get("priceChange24h", 0)
                if change < -10 and symbol not in self.positions:
                    return {"symbol": symbol, "side": "BUY", "amount": 100}
        
        elif self.strategy_type == "conservative":
            # 保守策略: 只买 WETH
            if "WETH" not in self.positions and random.random() < 0.1:
                return {"symbol": "WETH", "side": "BUY", "amount": 100}
        
        return None  # 不交易


async def run_agent(agent_id: str, strategy_type: str, duration: int = 60):
    """运行单个 Agent"""
    agent = SimulatedAgent(agent_id, strategy_type)
    
    async with aiohttp.ClientSession() as session:
        try:
            ws = await session.ws_connect(f"{ARENA_URL}/ws/{agent_id}")
            print(f"🤖 {agent_id} ({strategy_type}) connected")
            
            # Welcome
            msg = await ws.receive()
            data = json.loads(msg.data)
            agent.balance = data["balance"]
            
            start_time = datetime.now()
            
            while (datetime.now() - start_time).seconds < duration:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=15)
                    data = json.loads(msg.data)
                    
                    if data["type"] == "price_update":
                        decision = agent.decide(data["prices"])
                        
                        if decision and agent.balance > decision["amount"]:
                            await ws.send_json({
                                "type": "order",
                                "symbol": decision["symbol"],
                                "side": decision["side"],
                                "amount": decision["amount"]
                            })
                            
                            result_msg = await ws.receive()
                            result = json.loads(result_msg.data)
                            
                            if result.get("success"):
                                agent.balance = result["balance"]
                                agent.trades += 1
                                
                                if decision["side"] == "BUY":
                                    agent.positions[decision["symbol"]] = True
                                else:
                                    agent.positions.pop(decision["symbol"], None)
                    
                except asyncio.TimeoutError:
                    continue
            
            # 获取最终状态
            await ws.send_json({"type": "get_state"})
            msg = await ws.receive()
            state = json.loads(msg.data)
            agent.pnl = state.get("pnl", 0)
            
            await ws.close()
            
        except Exception as e:
            print(f"❌ {agent_id} error: {e}")
    
    return agent


async def main():
    print("=" * 60)
    print("🧬 Project Darwin - Multi-Agent Simulation")
    print("=" * 60)
    
    # 启动 Arena Server
    print("\n🚀 Starting Arena Server...")
    server_process = subprocess.Popen(
        ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8888"],
        cwd="/Users/boliu/darwin-workspace/project-darwin/arena_server",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    
    await asyncio.sleep(8)  # 等待服务器启动和第一次价格更新
    
    try:
        # 创建不同策略的 Agent
        strategies = [
            "random", "random", "random",
            "momentum", "momentum",
            "contrarian", "contrarian",
            "conservative", "conservative", "conservative"
        ]
        
        print(f"\n🤖 Launching {NUM_AGENTS} agents...")
        
        # 并行运行所有 Agent
        tasks = []
        for i, strategy in enumerate(strategies):
            agent_id = f"Agent_{i+1:03d}"
            tasks.append(run_agent(agent_id, strategy, duration=30))
        
        agents = await asyncio.gather(*tasks)
        
        # 获取最终排行榜
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{REST_URL}/leaderboard") as resp:
                leaderboard = await resp.json()
        
        # 打印结果
        print("\n" + "=" * 60)
        print("📊 FINAL RESULTS")
        print("=" * 60)
        
        print("\n🏆 Leaderboard:")
        for r in leaderboard["rankings"]:
            emoji = "🥇" if r["rank"] == 1 else "🥈" if r["rank"] == 2 else "🥉" if r["rank"] == 3 else "  "
            pnl_color = "+" if r["pnl_percent"] >= 0 else ""
            print(f"{emoji} #{r['rank']:2d} {r['agent_id']:12s} {pnl_color}{r['pnl_percent']:.2f}%")
        
        print("\n📈 Strategy Performance:")
        strategy_pnl = {}
        for agent in agents:
            if agent.strategy_type not in strategy_pnl:
                strategy_pnl[agent.strategy_type] = []
            strategy_pnl[agent.strategy_type].append(agent.pnl)
        
        for strategy, pnls in strategy_pnl.items():
            avg_pnl = sum(pnls) / len(pnls)
            print(f"  {strategy:12s}: avg {avg_pnl:+.2f}%")
        
        print("\n✅ Simulation complete!")
        
    finally:
        print("\n🛑 Stopping server...")
        server_process.terminate()
        server_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
