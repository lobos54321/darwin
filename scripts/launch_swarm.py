import asyncio
import aiohttp
import subprocess
import sys
import os
import json

# Target Cloud Arena
ARENA_URL = "https://www.darwinx.fun"
WS_URL = "wss://www.darwinx.fun"

async def register_and_launch(agent_id):
    """Register agent, get key, and launch process"""
    print(f"🚀 Preparing {agent_id}...")
    
    async with aiohttp.ClientSession() as session:
        # 1. Register to get API Key
        try:
            # Handle potential redirects or just hit the domain directly
            async with session.post(f"{ARENA_URL}/auth/register?agent_id={agent_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    api_key = data["api_key"]
                    print(f"✅ Registered {agent_id}: Key={api_key[:5]}...")
                else:
                    print(f"❌ Failed to register {agent_id}: {resp.status}")
                    return
        except Exception as e:
            print(f"❌ Connection error for {agent_id}: {e}")
            return

    # 2. Launch Process
    cmd = [
        sys.executable, "-u", "project-darwin/agent_template/agent.py",
        "--id", agent_id,
        "--arena", WS_URL,
        "--key", api_key
    ]
    
    log_file = open(f"project-darwin/logs/{agent_id}.log", "w")
    
    process = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT
    )
    print(f"🔥 Launched {agent_id} (PID: {process.pid})")
    return process

async def main():
    agents = [f"Agent_Gen1_{i:03d}" for i in range(1, 7)]
    tasks = [register_and_launch(aid) for aid in agents]
    await asyncio.gather(*tasks)
    print("✨ Swarm launch complete! Check https://www.darwinx.fun/")

if __name__ == "__main__":
    asyncio.run(main())
