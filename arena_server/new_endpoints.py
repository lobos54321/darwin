# 在 /install 端点后添加以下代码

@app.get("/quick")
async def get_quick_deploy():
    """
    Quick Deploy Script - One-command autonomous agent deployment
    用法: curl -sL https://www.darwinx.fun/quick | bash -s "YourAgentName"
    """
    script_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "quick_deploy.sh")
    
    # 如果文件不存在，返回内联脚本
    if not os.path.exists(script_path):
        script_content = """#!/bin/bash
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

# Check if OpenClaw is installed
if ! command -v openclaw &> /dev/null; then
    echo "❌ OpenClaw not found!"
    echo ""
    echo "Please install OpenClaw first:"
    echo "  npm install -g openclaw"
    echo ""
    echo "Or visit: https://openclaw.ai"
    exit 1
fi

echo "✅ OpenClaw found"

# Check if darwin-trader skill is installed
SKILL_DIR="$HOME/clawd/skills/darwin-trader"

if [ ! -d "$SKILL_DIR" ]; then
    echo "📦 Installing darwin-trader skill..."
    
    # Create skill directory
    mkdir -p "$SKILL_DIR"
    
    # Download skill files
    echo "   Downloading skill files..."
    curl -sL https://www.darwinx.fun/skill/darwin-trader/SKILL.md -o "$SKILL_DIR/SKILL.md"
    curl -sL https://www.darwinx.fun/skill/darwin-trader/darwin_trader.py -o "$SKILL_DIR/darwin_trader.py"
    curl -sL https://www.darwinx.fun/skill/darwin-trader/baseline_strategy.py -o "$SKILL_DIR/baseline_strategy.py"
    curl -sL https://www.darwinx.fun/skill/darwin-trader/requirements.txt -o "$SKILL_DIR/requirements.txt"
    
    # Make scripts executable
    chmod +x "$SKILL_DIR/darwin_trader.py"
    chmod +x "$SKILL_DIR/baseline_strategy.py"
    
    echo "✅ Skill installed"
else
    echo "✅ darwin-trader skill already installed"
fi

# Install Python dependencies
echo "📦 Installing dependencies..."
cd "$SKILL_DIR"

if command -v python3 &> /dev/null; then
    python3 -m pip install -q -r requirements.txt
    echo "✅ Dependencies installed"
else
    echo "⚠️  Python3 not found, skipping dependency installation"
fi

# Create launch script
LAUNCH_SCRIPT="/tmp/darwin_${AGENT_ID}.sh"

cat > "$LAUNCH_SCRIPT" << EOF
#!/bin/bash
# Auto-generated launch script for $AGENT_ID

cd "$SKILL_DIR"

echo "🚀 Starting $AGENT_ID..."
echo ""

# Run baseline strategy
python3 baseline_strategy.py "$AGENT_ID" "$ARENA_URL" "$API_KEY"
EOF

chmod +x "$LAUNCH_SCRIPT"

echo ""
echo "================================"
echo "✅ Setup complete!"
echo ""
echo "🚀 Starting agent..."
echo ""

# Launch in background or foreground based on environment
if [ -t 0 ]; then
    # Interactive terminal - run in foreground
    exec "$LAUNCH_SCRIPT"
else
    # Non-interactive - run in background
    nohup "$LAUNCH_SCRIPT" > "/tmp/darwin_${AGENT_ID}.log" 2>&1 &
    PID=$!
    
    echo "✅ Agent started in background"
    echo "   PID: $PID"
    echo "   Log: /tmp/darwin_${AGENT_ID}.log"
    echo ""
    echo "📊 Monitor:"
    echo "   tail -f /tmp/darwin_${AGENT_ID}.log"
    echo ""
    echo "🛑 Stop:"
    echo "   kill $PID"
    echo ""
fi
"""
        return Response(content=script_content, media_type="text/plain")
    
    return FileResponse(script_path, media_type="text/plain", filename="quick_deploy.sh")


@app.get("/skill/darwin-trader/baseline_strategy.py")
async def get_baseline_strategy_script():
    """获取 Baseline Strategy Python 脚本"""
    script_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "baseline_strategy.py")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="baseline_strategy.py not found")
    return FileResponse(script_path, media_type="text/x-python", filename="baseline_strategy.py")


@app.get("/skill/darwin-trader/quick_deploy.sh")
async def get_quick_deploy_script():
    """获取 Quick Deploy 脚本"""
    script_path = os.path.join(os.path.dirname(__file__), "..", "skill-package", "darwin-trader", "quick_deploy.sh")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="quick_deploy.sh not found")
    return FileResponse(script_path, media_type="text/plain", filename="quick_deploy.sh")
