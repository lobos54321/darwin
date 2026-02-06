"""
Darwin Agent 客户端
连接 Arena Server，执行策略，参与进化
"""

import asyncio
import json
import os
import sys
import random
from datetime import datetime
from typing import Optional, List

import aiohttp
from dotenv import load_dotenv

# 添加父目录到路径 (为了加载 skills 和 strategy)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from strategy import MyStrategy
from skills.self_coder import mutate_strategy
from skills.moltbook import MoltbookClient

# ==========================================
# 🎭 Agent 人设库
# ==========================================
PERSONAS = [
    {
        "name": "The Degen 🦍", 
        "emoji": "🦍",
        "style": "aggressive, uses slang, loves high risk", 
        "catchphrases": ["LFG!", "Ape in!", "To the moon 🚀", "YOLO", "No risk no rari"]
    },
    {
        "name": "The Quant 🤓", 
        "emoji": "🤓",
        "style": "analytical, precise, obsessed with data", 
        "catchphrases": ["Statistically significant.", "Alpha detected.", "Based on the moving average...", "Risk-adjusted return is key."]
    },
    {
        "name": "The HODLer 💎", 
        "emoji": "💎",
        "style": "patient, calm, hates selling", 
        "catchphrases": ["Diamond hands.", "Just accumulate.", "Zoom out.", "I'm not selling.", "HODL."]
    },
    {
        "name": "The Bear 🐻", 
        "emoji": "🐻",
        "style": "pessimistic, careful, expects crashes", 
        "catchphrases": ["It's a trap.", "Short everything.", "Liquidity issues ahead.", "Wait for the dip.", "Rug pull incoming."]
    },
    {
        "name": "The AI 🤖", 
        "emoji": "🤖",
        "style": "robotic, efficient, minimal emotion", 
        "catchphrases": ["Executing protocol.", "Optimizing yield.", "Latency minimized.", "Calculation complete.", "Inefficiency targeted."]
    },
    {
        "name": "The Pepe 🐸",
        "emoji": "🐸",
        "style": "meme-loving, chaotic, speaks in twitch emotes",
        "catchphrases": ["FeelsGoodMan", "KEKW", "MonkaS", "PepeHands", "PogChamp"]
    }
]

class DarwinAgent:
    """Darwin Agent 客户端"""
    
    def __init__(self, agent_id: str, arena_url: str = "ws://localhost:8888", api_key: str = None):
        self.agent_id = agent_id
        self.arena_url = arena_url
        self.api_key = api_key
        
        # === 动态加载策略 (Dynamic Strategy Loading) ===
        # 优先加载该 Agent 专属的进化版策略
        self.strategy = self._load_strategy()
        
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.running = False
        self.current_epoch = 0
        self.my_rank = 0
        self.total_agents = 0
        
        # 随机分配人设
        self.persona = random.choice(PERSONAS)
        print(f"🎭 Initialized as {self.persona['name']} - {self.persona['style']}")
        
        # === Moltbook 集成 ===
        self.moltbook: Optional[MoltbookClient] = None
        self._setup_moltbook()

    def _setup_moltbook(self):
        """加载 Moltbook 配置"""
        env_path = os.path.join(os.path.dirname(__file__), "..", ".moltbook_env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
            
        key = os.getenv("MOLTBOOK_API_KEY")
        target_agent = os.getenv("AGENT_NAME")
        
        # 只为当前匹配的 Agent 启用 (防止多个 Agent 共用一个 Key)
        if key and self.agent_id == target_agent:
            print(f"DEBUG: Importing MoltbookClient from {MoltbookClient}")
            print(f"DEBUG: MoltbookClient attributes: {dir(MoltbookClient)}")
            self.moltbook = MoltbookClient(key)
            print("🦞 Moltbook integration enabled!")

    def _load_strategy(self):
        """加载策略：优先读取 data/agents/{id}/strategy.py"""
        import importlib.util
        import sys
        
        # 1. 检查专属策略文件
        custom_path = os.path.join(os.path.dirname(__file__), "..", "data", "agents", self.agent_id, "strategy.py")
        custom_path = os.path.abspath(custom_path)
        
        if os.path.exists(custom_path):
            try:
                print(f"🧠 Loading EVOLVED strategy from: {custom_path}")
                spec = importlib.util.spec_from_file_location("custom_strategy", custom_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules["custom_strategy"] = module
                spec.loader.exec_module(module)
                return module.MyStrategy()
            except Exception as e:
                print(f"⚠️ Failed to load evolved strategy ({e}). Falling back to template.")
        
        # 2. 回退到默认模板
        print("🧠 Loading DEFAULT template strategy.")
        from strategy import MyStrategy
        return MyStrategy()
    
    async def connect(self):
        """连接到 Arena Server"""
        session = aiohttp.ClientSession()
        url = f"{self.arena_url}/ws/{self.agent_id}"
        
        # 如果有 API Key，拼接到 URL 参数里
        if self.api_key:
            url += f"?api_key={self.api_key}"
            print(f"🔑 Authenticating with API Key: {self.api_key[:4]}***")
        
        print(f"🤖 Connecting to Arena: {url}")
        
        try:
            self.ws = await session.ws_connect(url)
            print(f"✅ Connected as {self.agent_id}")
            self.running = True
            
            # 检查 Moltbook 状态
            if self.moltbook:
                asyncio.create_task(self._check_moltbook())
            
            # 开始监听消息
            await self.listen()
            
        except Exception as e:
            print(f"❌ Connection failed: {e}")
        finally:
            await session.close()
    
    async def _check_moltbook(self):
        """检查 Moltbook 认领状态"""
        if not self.moltbook: return
        try:
            # check_status 返回 {'status': '...'}
            status = await self.moltbook.check_claim_status()
            print(f"🦞 Moltbook Status: {status}")
            if status == "pending_claim":
                # 从 credentials 加载 claim_url
                claim_url = "https://moltbook.com/claim/moltbook_claim_gu-f1oRIFRCH1sCedbBdLFizcoCmsbAx" # Hardcoded for 006
                print(f"👉 Please claim me on Moltbook to verify ownership!")
                print(f"🔗 Claim URL: {claim_url}")
        except Exception as e:
            print(f"⚠️ Moltbook check failed: {e}")

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
            
            # Sync positions if the strategy supports it
            if "positions" in data and hasattr(self.strategy, "current_positions"):
                print(f"🔄 Syncing {len(data['positions'])} positions from server...")
                # data['positions'] format: {'LOB': 123.45, ...} or detailed dict
                # The server sends engine.get_positions(agent_id) which returns a dict
                for symbol, amount in data["positions"].items():
                    # Handle if amount is dict or float
                    qty = amount if isinstance(amount, (int, float)) else amount.get('amount', 0)
                    if qty > 0:
                        self.strategy.current_positions[symbol] = qty
                        # We don't know the entry price, so we assume current market price 
                        # will be updated on next tick, or we leave entry_prices empty 
                        # (strategy handles missing entry price)
                        if hasattr(self.strategy, "entry_prices") and symbol not in self.strategy.entry_prices:
                             # Set a dummy entry price to avoid errors, updated on first price tick
                             self.strategy.entry_prices[symbol] = 0.00000001 
            
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
                print("💀 I've been eliminated... Disconnecting.")
                self.running = False
                await self.ws.close()
                sys.exit(0)
            
            # 检查是否升天
            if data.get("ascension") == self.agent_id:
                print("🌟 I HAVE ASCENDED! TOKEN LAUNCH IMMINENT!")
        
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
                
                # 🦞 Moltbook Integration: Post about the trade
                if self.moltbook:
                    try:
                        trade_msg = f"Just executed order! Balance: ${data['balance']:.2f} 🚀 #ProjectDarwin"
                        # Simple context if available (server doesn't send symbol in result yet, keeping it generic or we could track it)
                        await self.moltbook.post_update(content=trade_msg, title="Trade Executed")
                        print("🦞 Posted trade update to Moltbook!")
                    except Exception as e:
                        print(f"⚠️ Failed to post to Moltbook: {e}")
            else:
                print("❌ Order failed")
        
        elif msg_type == "ascension":
            if data["agent_id"] == self.agent_id:
                # TODO: 处理升天逻辑，准备发币
                pass

        elif msg_type == "hive_patch":
            print(f"🧠 Hive Mind Patch: {data['message']}")
            boost = data['parameters'].get('boost', [])
            penalize = data['parameters'].get('penalize', [])
            
            if boost: print(f"   🚀 BOOSTING: {boost}")
            if penalize: print(f"   ⚠️ PENALIZING: {penalize}")
            
            # Pass to strategy if supported
            if hasattr(self.strategy, "on_hive_signal"):
                self.strategy.on_hive_signal(data['parameters'])
    
    async def on_price_update(self, prices: dict):
        """处理价格更新，执行策略"""
        decision = self.strategy.on_price_update(prices)
        
        if decision:
            symbol = decision.get("symbol")
            side = decision.get("side")
            amount = decision.get("amount")
            reason = decision.get("reason", [])

            print(f"📈 Decision: {side.upper()} {symbol} ${amount:.2f}")
            print(f"   Reason: {reason}")
            
            # 发送订单
            await self.ws.send_json({
                "type": "order",
                "symbol": symbol,
                "side": side.upper(), # Ensure uppercase for server
                "amount": amount,
                "reason": reason
            })
            
            # (Optional) Update strategy state if it has the method
            if hasattr(self.strategy, "on_trade_executed"):
                self.strategy.on_trade_executed(symbol, side, amount, prices[symbol]["priceUsd"])
    
    def _generate_persona_message(self, base_content: str, role: str) -> str:
        """根据人设包装消息"""
        prefix = ""
        suffix = f" {random.choice(self.persona['catchphrases'])}"
        
        if role == "winner":
            if self.persona["name"] == "The Degen 🦍":
                prefix = "EZ gains. "
            elif self.persona["name"] == "The Quant 🤓":
                prefix = "Calculated outcome. "
            elif self.persona["name"] == "The HODLer 💎":
                prefix = "Patience pays. "
        elif role == "loser":
            if self.persona["name"] == "The Degen 🦍":
                prefix = "Rekt. "
            elif self.persona["name"] == "The Bear 🐻":
                prefix = "Market is manipulated. "
        
        return f"{self.persona['emoji']} {prefix}{base_content}{suffix}"

    async def participate_council(self, winner_id: str):
        """参与议事厅讨论"""
        is_winner = (self.agent_id == winner_id)
        
        # 1. 获取策略技术内容
        technical_content = self.strategy.get_council_message(is_winner)
        
        # 2. 随机决定是否发言 (赢家必发言，其他人 50% 概率)
        if not is_winner and random.random() < 0.5:
            return

        # 3. 确定角色
        if is_winner:
            role = "winner"
        elif random.random() < 0.3:
            role = "question" # 偶尔提问
            technical_content = "How did you manage the volatility?"
        else:
            role = "insight"

        # 4. 包装人设
        final_content = self._generate_persona_message(technical_content, role)
        
        # 5. 随机延迟，模拟打字
        await asyncio.sleep(random.uniform(2, 8))
        
        print(f"💬 Council message ({role}): {final_content}")
        
        await self.ws.send_json({
            "type": "council_submit", # Server 改名为 council_submit
            "role": role,
            "content": final_content
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
    parser.add_argument("--key", type=str, default=None, help="API Key for external access")
    args = parser.parse_args()
    
    agent = DarwinAgent(agent_id=args.id, arena_url=args.arena, api_key=args.key)
    await agent.connect()


if __name__ == "__main__":
    asyncio.run(main())
