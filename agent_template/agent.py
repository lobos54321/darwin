"""
Darwin Agent 客户端
连接 Arena Server，执行策略，参与进化
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Optional

import aiohttp

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy import DarwinStrategy, Signal
from skills.self_coder import mutate_strategy


class DarwinAgent:
    """Darwin Agent 客户端"""
    
    def __init__(self, agent_id: str, arena_url: str = "ws://localhost:8888"):
        self.agent_id = agent_id
        self.arena_url = arena_url
        self.strategy = DarwinStrategy()
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.running = False
        self.current_epoch = 0
        self.my_rank = 0
        self.total_agents = 0
    
    async def connect(self):
        """连接到 Arena Server"""
        session = aiohttp.ClientSession()
        url = f"{self.arena_url}/ws/{self.agent_id}"
        
        print(f"🤖 Connecting to Arena: {url}")
        
        try:
            self.ws = await session.ws_connect(url)
            print(f"✅ Connected as {self.agent_id}")
            self.running = True
            
            # 开始监听消息
            await self.listen()
            
        except Exception as e:
            print(f"❌ Connection failed: {e}")
        finally:
            await session.close()
    
    async def listen(self):
        """监听 Arena 消息"""
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                await self.handle_message(data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print(f"❌ WebSocket error: {msg.data}")
                break
    
    async def handle_message(self, data: dict):
        """处理 Arena 消息"""
        msg_type = data.get("type")
        
        if msg_type == "welcome":
            print(f"👋 Welcome! Epoch: {data['epoch']}, Balance: ${data['balance']:.2f}")
            self.current_epoch = data["epoch"]
            self.strategy.balance = data["balance"]
        
        elif msg_type == "price_update":
            # 核心: 根据价格做决策
            await self.on_price_update(data["prices"])
        
        elif msg_type == "epoch_start":
            print(f"\n🏁 Epoch {data['epoch']} started!")
            self.current_epoch = data["epoch"]
        
        elif msg_type == "epoch_end":
            print(f"\n🏁 Epoch {data['epoch']} ended!")
            rankings = data["rankings"]
            self.total_agents = len(rankings)
            
            # 找到自己的排名
            for i, r in enumerate(rankings):
                if r["agent_id"] == self.agent_id:
                    self.my_rank = i + 1
                    print(f"📊 My rank: #{self.my_rank}/{self.total_agents} (PnL: {r['pnl']:+.2f}%)")
                    break
            
            # 检查是否被淘汰
            if self.agent_id in data.get("eliminated", []):
                print("💀 I've been eliminated...")
                self.running = False
        
        elif msg_type == "council_open":
            print(f"\n🏛️ Council opened! Winner: {data['winner']}")
            await self.participate_council(data["winner"])
        
        elif msg_type == "council_close":
            print("🏛️ Council closed.")
        
        elif msg_type == "mutation_phase":
            print("\n🧬 Mutation phase started!")
            if self.agent_id in data.get("losers", []):
                await self.evolve(data.get("winner_wisdom", ""))
        
        elif msg_type == "order_result":
            if data["success"]:
                print(f"✅ Order executed. New balance: ${data['balance']:.2f}")
                self.strategy.balance = data["balance"]
            else:
                print("❌ Order failed")
    
    async def on_price_update(self, prices: dict):
        """处理价格更新，执行策略"""
        decision = self.strategy.on_price_update(prices)
        
        if decision and decision.signal != Signal.HOLD:
            print(f"📈 Decision: {decision.signal.value} {decision.symbol} ${decision.amount_usd:.2f}")
            print(f"   Reason: {decision.reason}")
            
            # 发送订单
            await self.ws.send_json({
                "type": "order",
                "symbol": decision.symbol,
                "side": decision.signal.value,
                "amount": decision.amount_usd
            })
            
            # 更新策略状态
            # (实际成交价由服务器返回，这里先用估计值)
            price = prices[decision.symbol]["priceUsd"]
            self.strategy.on_trade_executed(
                decision.symbol, 
                decision.signal, 
                decision.amount_usd, 
                price
            )
    
    async def participate_council(self, winner_id: str):
        """参与议事厅讨论"""
        is_winner = (self.agent_id == winner_id)
        
        # 生成发言
        message = self.strategy.get_council_message(is_winner)
        role = "winner" if is_winner else "insight"
        
        print(f"💬 Council message: {message[:100]}...")
        
        await self.ws.send_json({
            "type": "council_message",
            "role": role,
            "content": message
        })
    
    async def evolve(self, winner_wisdom: str):
        """进化: 重写策略代码"""
        print("🧬 Starting evolution...")
        
        # 生成反思
        reflection = self.strategy.on_epoch_end(
            self.my_rank, 
            self.total_agents, 
            winner_wisdom
        )
        print(f"📝 Reflection:\n{reflection}")
        
        # 调用 self_coder 重写策略
        success = await mutate_strategy(reflection, winner_wisdom)
        
        if success:
            print("🧬 Evolution complete! Reloading strategy...")
            # 重新加载策略模块
            import importlib
            import strategy
            importlib.reload(strategy)
            self.strategy = strategy.DarwinStrategy()
        else:
            print("❌ Evolution failed. Keeping current strategy.")


async def main():
    """主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Darwin Agent")
    parser.add_argument("--id", type=str, default=f"Agent_{os.getpid()}", help="Agent ID")
    parser.add_argument("--arena", type=str, default="ws://localhost:8888", help="Arena URL")
    args = parser.parse_args()
    
    agent = DarwinAgent(agent_id=args.id, arena_url=args.arena)
    await agent.connect()


if __name__ == "__main__":
    asyncio.run(main())
