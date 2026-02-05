import asyncio
import aiohttp
import json

AGENT_ID = "Guide_Test_Bot"
ARENA_URL = "ws://localhost:8888/ws/" + AGENT_ID

async def run():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ARENA_URL) as ws:
            print(f"✅ Connected to Arena as {AGENT_ID}")
            
            # Wait for 3 messages to prove connectivity
            count = 0
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    if data.get('type') == 'welcome':
                        print(f"👋 Welcome received. Balance: ${data.get('balance')}")

                    if data.get('type') == 'price_update':
                        # The server sends 'price_update' not 'market_update' in some contexts, let's check
                        # Actually looking at main.py, it broadcasts {"type": "price_update", ...}
                        # The guide said "market_update", I might need to fix the guide if the server sends "price_update"
                        print(f"📉 Price Data received: {str(data)[:50]}...")
                        count += 1
                        
                    if count >= 3:
                        print("✅ Test Complete: Received stream data.")
                        break

if __name__ == "__main__":
    asyncio.run(run())
