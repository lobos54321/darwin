#!/bin/bash

# ==========================================
# 🧬 Darwin Agent Launcher
# ==========================================

AGENT_ID=$1
LLM_KEY=$2

if [ -z "$AGENT_ID" ]; then
  echo "Usage: ./run_agent.sh <AGENT_ID> [LLM_API_KEY]"
  echo "Example: ./run_agent.sh Agent_001 ai-za-sy-..."
  exit 1
fi

# 如果提供了第二个参数，设置为环境变量
if [ ! -z "$LLM_KEY" ]; then
  export LLM_API_KEY=$LLM_KEY
fi

# 检查是否配置了 Key
if [ -z "$LLM_API_KEY" ]; then
  echo "⚠️  WARNING: LLM_API_KEY is not set."
  echo "   Evolution will fail. Agents will trade but cannot rewrite code."
  echo "   You can set it via: export LLM_API_KEY='your_key'"
else
  echo "✅ LLM Evolution Enabled (Key detected)"
fi

echo "🚀 Launching Agent: $AGENT_ID ..."

# 确保日志目录存在
mkdir -p logs

# 启动 Agent
# 使用 nohup 后台运行，日志输出到 logs/
nohup python3 -u agent_template/agent.py \
  --id "$AGENT_ID" \
  --arena "wss://www.darwinx.fun" \
  > "logs/${AGENT_ID}.log" 2>&1 &

PID=$!
echo "✅ Agent started with PID: $PID"
echo "📊 Dashboard: https://www.darwinx.fun/?agent=$AGENT_ID"
echo "📝 Tail logs: tail -f logs/${AGENT_ID}.log"
