#!/usr/bin/env python3
"""
Inject test trades into the Darwin Arena to populate the frontend.
Run this after the arena server is started.
"""

import asyncio
import json
import random
import aiohttp

ARENA_URL = "ws://localhost:8888"
SYMBOLS = ["CLANKER", "MOLT", "LOB", "WETH"]

async def inject_trades():
    """Connect as an agent and make some trades to populate the system."""
    
    agents_to_activate = [
        "Agent_006",
        "Agent_007", 
        "AlphaAlpha",
        "BetaBot",
        "GammaGuru",
        "DeltaDegen"
    ]
    
    for agent_id in agents_to_activate:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(f"{ARENA_URL}/ws/{agent_id}") as ws:
                    print(f"🔌 Connected as {agent_id}")
                    
                    # Wait for welcome/price update
                    try:
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                        print(f"📨 Received: {msg.get('type', 'unknown')}")
                    except:
                        pass
                    
                    # Make 2-3 random trades per agent
                    num_trades = random.randint(2, 4)
                    for _ in range(num_trades):
                        symbol = random.choice(SYMBOLS)
                        side = random.choice(["buy", "sell"])
                        amount = round(random.uniform(10, 50), 2)
                        
                        order = {
                            "type": "order",
                            "symbol": symbol,
                            "side": side,
                            "amount": amount,
                            "reason": ["INJECT_TEST", "WARMUP"]
                        }
                        
                        await ws.send_json(order)
                        print(f"📤 {agent_id}: {side.upper()} ${amount} of {symbol}")
                        
                        # Wait for response
                        try:
                            resp = await asyncio.wait_for(ws.receive_json(), timeout=3)
                            success = resp.get("success", False)
                            msg = resp.get("message", "")
                            print(f"   → {'✅' if success else '❌'} {msg}")
                        except:
                            pass
                        
                        await asyncio.sleep(0.3)
                    
                    # Close connection
                    await ws.close()
                    print(f"✅ {agent_id} done\n")
                    
        except Exception as e:
            print(f"❌ {agent_id} error: {e}")
        
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    print("🚀 Injecting test trades into Darwin Arena...")
    asyncio.run(inject_trades())
    print("\n✨ Done! Check the frontend for activity.")
