
import asyncio
import sys
import os
from dotenv import load_dotenv

# Load env vars first
load_dotenv("project-darwin/.env")

# Setup paths
sys.path.insert(0, os.path.abspath("project-darwin"))
sys.path.insert(0, os.path.abspath("project-darwin/arena_server"))

from arena_server.evolution import MutationEngine
from arena_server.matching import AgentAccount

async def force_evolve():
    print("🧪 Initializing Surgical Mutation for Agent_006...")
    
    # Mock Agent State (Bankrupt)
    agent = AgentAccount(agent_id="Agent_006")
    agent.balance = 0.09 # Critical state
    
    # Mock Winner Wisdom
    winner_wisdom = "In this crash, CASH IS KING. Do not buy dips unless they are -10% deep. Wait for capitulation."
    
    engine = MutationEngine()
    
    print("🚀 Triggering LLM...")
    success = await engine.mutate_agent(agent, winner_wisdom)
    
    if success:
        print("✅ SUCCESS: Agent_006 has been mutated!")
    else:
        print("❌ FAILED: Mutation error.")

if __name__ == "__main__":
    asyncio.run(force_evolve())
