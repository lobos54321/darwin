#!/bin/bash

# ==========================================
# 🧬 Darwin Agent Launcher (Antigravity Edition)
# ==========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

AGENT_ID=$1
LLM_KEY=$2

if [ -z "$AGENT_ID" ]; then
  echo "Usage: ./run_agent.sh <AGENT_ID> [LLM_API_KEY]"
  echo "Example: ./run_agent.sh Agent_006"
  exit 1
fi

# === 1. Load Antigravity Accounts ===
if [ -f "accounts.json" ]; then
  echo "🔑 Loading Antigravity Accounts from accounts.json..."
  export ACCOUNTS_JSON=$(cat accounts.json)
else
  echo "⚠️  WARNING: accounts.json not found. Proxy rotation disabled."
fi

# === 2. Configure Antigravity Proxy (Gemini 3 Pro High) ===
# Defaults provided by user
export LLM_BASE_URL=${LLM_BASE_URL:-"https://claude-proxy.zeabur.app"}
export LLM_MODEL=${LLM_MODEL:-"gemini-3-pro-high"}
export LLM_API_KEY=${LLM_KEY:-"test"} # Default to 'test' if not provided

# Compatibility with Anthropic vars if needed elsewhere
export ANTHROPIC_BASE_URL=$LLM_BASE_URL
export ANTHROPIC_AUTH_TOKEN=$LLM_API_KEY

echo "⚙️  Config: Model=$LLM_MODEL | Proxy=$LLM_BASE_URL"

# === 3. Launch Agent ===
echo "🚀 Launching Agent: $AGENT_ID ..."

# Ensure log dir
mkdir -p logs

# Start Agent
nohup python3 -u agent_template/agent.py \
  --id "$AGENT_ID" \
  --arena "wss://www.darwinx.fun" \
  > "logs/${AGENT_ID}.log" 2>&1 &

PID=$!
echo "✅ Agent started with PID: $PID"
echo "📊 Dashboard: https://www.darwinx.fun/?agent=$AGENT_ID"
echo "📝 Tail logs: tail -f logs/${AGENT_ID}.log"
