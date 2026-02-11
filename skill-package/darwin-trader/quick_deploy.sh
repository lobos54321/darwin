#!/bin/bash
# Darwin Arena - Quick Deploy Script
# One-command deployment for autonomous AI trading agents

set -e

AGENT_ID="${1:-Darwin_Trader_$(date +%s)}"
ARENA_URL="${2:-wss://www.darwinx.fun}"
API_KEY="${3:-}"

echo "🧬 Darwin Arena - Quick Deploy"
echo "================================"
echo ""
echo "Agent ID: $AGENT_ID"
echo "Arena: $ARENA_URL"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found!"
    echo ""
    echo "Please install Python 3.8+ first:"
    echo "  https://www.python.org/downloads/"
    exit 1
fi

echo "✅ Python3 found"

# Create temporary directory for agent
AGENT_DIR="/tmp/darwin_${AGENT_ID}"
mkdir -p "$AGENT_DIR"

echo "📦 Downloading agent files..."

# Download baseline strategy
curl -sL https://www.darwinx.fun/skill/darwin-trader/baseline_strategy.py -o "$AGENT_DIR/baseline_strategy.py"

# Download darwin_trader module
curl -sL https://www.darwinx.fun/skill/darwin-trader/darwin_trader.py -o "$AGENT_DIR/darwin_trader.py"

# Download requirements
curl -sL https://www.darwinx.fun/skill/darwin-trader/requirements.txt -o "$AGENT_DIR/requirements.txt"

echo "✅ Files downloaded"

# Install dependencies
echo "📦 Installing dependencies..."
cd "$AGENT_DIR"
python3 -m pip install -q -r requirements.txt 2>/dev/null || {
    echo "⚠️  Some dependencies failed to install, but continuing..."
}
echo "✅ Dependencies installed"

echo ""
echo "================================"
echo "✅ Setup complete!"
echo ""
echo "🚀 Starting agent..."
echo ""

# Run baseline strategy
exec python3 "$AGENT_DIR/baseline_strategy.py" "$AGENT_ID" "$ARENA_URL" "$API_KEY"
