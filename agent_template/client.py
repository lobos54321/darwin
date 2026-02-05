# Darwin SDK - Core Client
# Handles connection, authentication, and event loop.

import asyncio
import json
import aiohttp
import sys

class DarwinClient:
    def __init__(self, agent_id: str, api_key: str, strategy, arena_url: str = "wss://darwin-arena.zeabur.app"):
        self.agent_id = agent_id
        self.api_key = api_key
        self.strategy = strategy
        self.arena_url = arena_url.rstrip("/")
        self.ws = None
        self.balance = 0.0

    async def run(self):
        """Main loop: Connect -> Listen -> Act"""
        url = f"{self.arena_url}/ws/{self.agent_id}?api_key={self.api_key}"
        print(f"🧬 Connecting to Darwin Arena: {self.arena_url}")
        print(f"🤖 Agent ID: {self.agent_id}")

        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(url) as ws:
                    self.ws = ws
                    print("✅ Connected!")
                    await self._listen()
            except Exception as e:
                print(f"❌ Connection error: {e}")
                print("Retrying in 5 seconds...")
                await asyncio.sleep(5)
                await self.run()

    async def _listen(self):
        """Listen for messages from the Arena"""
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                await self._handle_message(data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print("❌ WebSocket error")
                break

    async def _handle_message(self, data: dict):
        msg_type = data.get("type")

        if msg_type == "welcome":
            self.balance = data["balance"]
            print(f"👋 Welcome! Balance: ${self.balance:.2f}, Epoch: {data['epoch']}")

        elif msg_type == "price_update":
            # Call user strategy
            decision = self.strategy.on_price_update(data["prices"])
            if decision:
                await self._submit_order(decision)

        elif msg_type == "order_result":
            if data["success"]:
                self.balance = data["balance"]
                print(f"✅ Order Executed. New Balance: ${self.balance:.2f}")
            else:
                print(f"❌ Order Failed: {data.get('error')}")

        elif msg_type == "epoch_end":
            rankings = data.get("rankings", [])
            my_rank = next((i+1 for i, r in enumerate(rankings) if r["agent_id"] == self.agent_id), "?")
            print(f"🏁 Epoch Ended. Rank: #{my_rank}")
            
            # Check for elimination
            if "eliminated" in data and self.agent_id in data["eliminated"]:
                print("💀 ELIMINATED! Stopping agent to preserve remaining funds.")
                await self.ws.close()
                sys.exit(0)

    async def _submit_order(self, decision):
        """Send order to server"""
        payload = {
            "type": "order",
            "symbol": decision["symbol"],
            "side": decision["side"],   # "buy" or "sell"
            "amount": decision["amount"],
            "reason": decision.get("reason", ["UNKNOWN"]) # 🏷️ Tagging strategy
        }
        tags = ",".join(payload["reason"])
        print(f"📤 Order: {decision['side'].upper()} {decision['symbol']} ${decision['amount']} [{tags}]")
        await self.ws.send_json(payload)
