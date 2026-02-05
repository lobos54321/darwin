import asyncio
import aiohttp
import os
import random
import sys
import subprocess
from typing import List

BASE_URL = "http://localhost:8888"
SWARM_SIZE = 10
ARCHETYPES = [
    "Degen_Ape", "Diamond_Hands", "Paper_Hands", "FOMO_Bot", 
    "Value_Investor", "Technical_Analyst", "Contrarian", 
    "Whale_Watcher", "Copy_Trader", "Chaos_Monkey"
]

async def register_agent(session, name: str) -> str:
    """Register agent and get API Key"""
    async with session.post(f"{BASE_URL}/auth/register?agent_id={name}") as resp:
        if resp.status == 200:
            data = await resp.json()
            return data["api_key"]
        return None

async def launch_swarm():
    print(f"🐝 Unleashing Swarm of {SWARM_SIZE} agents...")
    
    # Ensure logs dir exists
    os.makedirs("../logs", exist_ok=True)
    
    async with aiohttp.ClientSession() as session:
        for i in range(SWARM_SIZE):
            archetype = ARCHETYPES[i % len(ARCHETYPES)]
            agent_id = f"{archetype}_{random.randint(100, 999)}"
            
            print(f"   Creating {agent_id}...", end=" ", flush=True)
            
            # 1. Register
            api_key = await register_agent(session, agent_id)
            
            if api_key:
                print(f"✅ Key: {api_key[:6]}... ", end=" ", flush=True)
                
                # 2. Launch Process
                # We use the template agent but pass the key
                cmd = [
                    "python3", "-u", "agent_template/agent.py",
                    "--id", agent_id,
                    "--key", api_key,
                    "--arena", "ws://localhost:8888"
                ]
                
                log_file = open(f"../logs/{agent_id}.log", "w")
                subprocess.Popen(cmd, stdout=log_file, stderr=log_file, cwd="..")
                print("🚀 Launched!")
                
            else:
                print("❌ Registration Failed")
                
    print("\n🐝 Swarm is active! Check the Dashboard.")

if __name__ == "__main__":
    # Fix working directory to be tools/
    if os.path.basename(os.getcwd()) != "tools":
        if os.path.exists("tools"):
            os.chdir("tools")
    
    asyncio.run(launch_swarm())
