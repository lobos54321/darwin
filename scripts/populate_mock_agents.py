import os
import json
import logging
import random

# Mock agents to populate the arena for mutation testing
MOCK_AGENTS = {
    "Agent_001": {"balance": 1250.0, "positions": {}},
    "Agent_002": {"balance": 1100.5, "positions": {}},
    "Agent_003": {"balance": 980.0, "positions": {}},
    "Agent_004": {"balance": 850.2, "positions": {}},
    "Agent_005": {"balance": 720.0, "positions": {}}
}

STATE_FILE = "project-darwin/data/arena_state.json"

def populate():
    if not os.path.exists(STATE_FILE):
        print("State file not found.")
        return
        
    with open(STATE_FILE, "r") as f:
        state = json.load(f)
    
    state["agents"] = MOCK_AGENTS
    
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"✅ Populated {len(MOCK_AGENTS)} agents into arena state.")

if __name__ == "__main__":
    populate()
