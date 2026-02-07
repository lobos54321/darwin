#!/bin/bash

# Project Darwin - Agent Swarm Launcher
# Spawns multiple agents to populate the arena

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🧬 Launching Darwin Agent Swarm..."

# Kill existing agents if any
pkill -f "python3 agent_template/agent.py"

# Function to spawn an agent
spawn_agent() {
    AGENT_ID=$1
    echo "🚀 Spawning $AGENT_ID..."
    # Run in background, log to file
    nohup python3 agent_template/agent.py --id "$AGENT_ID" > "logs/$AGENT_ID.log" 2>&1 &
}

# Ensure logs dir exists
mkdir -p logs

# Spawn initial batch
spawn_agent "AlphaAlpha"
spawn_agent "BetaBot"
spawn_agent "GammaGuru"
spawn_agent "DeltaDegen"
spawn_agent "OmegaOne"
spawn_agent "ZetaZero"

echo "✅ 6 Agents deployed into the Arena!"
echo "📜 Logs are in logs/ directory"
echo "👀 Check dashboard at http://localhost:8888/live"
