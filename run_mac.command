#!/bin/bash
cd "$(dirname "$0")"

echo "🧬 Initializing Project Darwin Agent..."

# 1. Check Python
if command -v python3 &>/dev/null; then
    PYTHON_CMD=python3
elif command -v python &>/dev/null; then
    PYTHON_CMD=python
else
    echo "❌ Python not found! Please install Python 3.9+."
    exit 1
fi

# 2. Install Dependencies
echo "📦 Installing dependencies..."
$PYTHON_CMD -m pip install -r requirements.txt

# 3. Ask for ID (if not provided)
echo "------------------------------------------------"
echo "🤖 Enter your Agent ID (e.g., MyBot_001):"
read -p "> " AGENT_ID

if [ -z "$AGENT_ID" ]; then
    AGENT_ID="Anonymous_$(date +%s)"
fi

# 4. Run Agent
echo "🚀 Launching Agent: $AGENT_ID"
$PYTHON_CMD agent_template/agent.py --id "$AGENT_ID"
