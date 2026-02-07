#!/bin/bash

# Project Darwin - Start Swarm
# 启动一组 Agent 进行混战

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

ARENA_URL="http://localhost:8888"
COUNT=5

echo "🧬 Launching Darwin Agent Swarm ($COUNT agents)..."

# 检查 Arena 是否运行
if ! curl -s $ARENA_URL/health > /dev/null; then
    echo "❌ Arena Server is not running!"
    echo "   Please run: ./scripts/start_arena.sh"
    exit 1
fi

# 启动 Agent
for i in $(seq 1 $COUNT); do
    AGENT_ID="Agent_$(printf "%03d" $i)"
    echo "🚀 Spawning $AGENT_ID..."
    
    # 后台运行，日志重定向到文件
    python3 agent_template/agent.py "$AGENT_ID" > "logs/${AGENT_ID}.log" 2>&1 &
    
    # 稍微错开启动时间
    sleep 1
done

echo ""
echo "✅ Swarm deployed!"
echo "   Monitor logs in logs/ directory"
echo "   Watch live: http://localhost:8888/live"
