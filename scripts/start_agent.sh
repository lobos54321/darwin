#!/bin/bash
# 启动测试 Agent

cd "$(dirname "$0")/../agent_template"

AGENT_ID=${1:-"Agent_$(date +%s)"}
ARENA_URL=${2:-"ws://localhost:8888"}

echo "🤖 Starting Darwin Agent: $AGENT_ID"
echo "   Arena: $ARENA_URL"
echo ""

python3 agent.py --id "$AGENT_ID" --arena "$ARENA_URL"
