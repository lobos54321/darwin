#!/usr/bin/env python3
"""
Darwin Arena Agent - Standalone launcher for OpenClaw skills.
"""

import asyncio
import argparse
import os
import sys
import random
import json
from datetime import datetime

# Add scripts dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import aiohttp
except ImportError:
    print("❌ Missing dependency. Run: pip3 install aiohttp")
    sys.exit(1)

from strategy import MyStrategy

# Persona library for fun
PERSONAS = [
    {"emoji": "🦍", "phrases": ["LFG!", "Ape in!", "YOLO"]},
    {"emoji": "🤓", "phrases": ["Statistically significant.", "Alpha detected."]},
    {"emoji": "💎", "phrases": ["Diamond hands.", "HODL.", "Just accumulate."]},
    {"emoji": "🐻", "phrases": ["It's a trap.", "Short everything."]},
    {"emoji": "🤖", "phrases": ["Executing protocol.", "Optimizing yield."]},
]


class DarwinAgent:
    def __init__(self, agent_id: str, arena_url: str):
        self.agent_id = agent_id
        self.arena_url = arena_url
        self.strategy = MyStrategy()
        self.persona = random.choice(PERSONAS)
        self.running = False
        self.api_key = None
        
    async def register(self, session):
        """Register with arena and get API key."""
        http_url = self.arena_url.replace("wss://", "https://").replace("ws://", "http://")
        async with session.post(f"{http_url}/auth/register?agent_id={self.agent_id}") as resp:
            if resp.status == 200:
                data = await resp.json()
                self.api_key = data.get("api_key")
                print(f"✅ Registered: {self.agent_id}")
                return True
            else:
                print(f"❌ Registration failed: {resp.status}")
                return False
    
    async def run(self):
        """Main agent loop."""
        self.running = True
        print(f"🧬 Darwin Agent '{self.agent_id}' starting...")
        print(f"🎭 Persona: {self.persona['emoji']}")
        print(f"🔗 Arena: {self.arena_url}")
        
        async with aiohttp.ClientSession() as session:
            # Register first
            if not await self.register(session):
                return
            
            ws_url = f"{self.arena_url}/ws/{self.agent_id}?api_key={self.api_key}"
            
            while self.running:
                try:
                    async with session.ws_connect(ws_url, heartbeat=30) as ws:
                        print(f"🔌 Connected to arena!")
                        
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self.handle_message(ws, json.loads(msg.data))
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                print(f"❌ WebSocket error: {ws.exception()}")
                                break
                                
                except aiohttp.ClientError as e:
                    print(f"⚠️ Connection lost: {e}")
                    await asyncio.sleep(5)
                except Exception as e:
                    print(f"❌ Error: {e}")
                    await asyncio.sleep(5)
    
    async def handle_message(self, ws, data):
        """Handle incoming messages from arena."""
        msg_type = data.get("type")
        
        if msg_type == "welcome":
            print(f"👋 Welcome received. Balance: ${data.get('balance', 1000)}")
            
        elif msg_type == "price_update":
            prices = data.get("prices", {})
            decision = self.strategy.on_price_update(prices)
            
            if decision:
                await ws.send_json({
                    "type": "order",
                    "symbol": decision["symbol"],
                    "side": decision["side"].upper(),
                    "amount": decision["amount"],
                    "reason": decision.get("reason", [])
                })
                print(f"📤 {decision['side'].upper()} ${decision['amount']} {decision['symbol']}")
                
        elif msg_type == "order_result":
            status = "✅" if data.get("success") else "❌"
            print(f"   {status} {data.get('message', '')}")
            
        elif msg_type == "hive_patch":
            print(f"🧠 Hive Mind: {data.get('message', '')}")
            if hasattr(self.strategy, 'on_hive_signal'):
                self.strategy.on_hive_signal(data.get("parameters", {}))
                
        elif msg_type == "epoch_end":
            rank = data.get("my_rank", "?")
            eliminated = data.get("eliminated", [])
            phrase = random.choice(self.persona["phrases"])
            print(f"🏁 Epoch ended! Rank: #{rank} {self.persona['emoji']} {phrase}")
            
            if self.agent_id in eliminated:
                print(f"💀 Eliminated... Reconnecting with evolved strategy.")


async def main():
    parser = argparse.ArgumentParser(description="Darwin Arena Agent")
    parser.add_argument("--agent_id", "-id", required=True, help="Your agent name")
    parser.add_argument("--arena", default=None, help="Arena WebSocket URL")
    args = parser.parse_args()
    
    arena_url = args.arena or os.environ.get("DARWIN_ARENA_URL", "wss://www.darwinx.fun")
    
    agent = DarwinAgent(args.agent_id, arena_url)
    
    try:
        await agent.run()
    except KeyboardInterrupt:
        print("\n👋 Agent shutting down...")
        agent.running = False


if __name__ == "__main__":
    asyncio.run(main())
