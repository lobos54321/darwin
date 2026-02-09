#!/bin/bash
# Darwin Arena - 批量启动OpenClaw Agents

AGENT_COUNT=${1:-3}  # 默认启动3个agents
ARENA_URL=${2:-"wss://www.darwinx.fun"}

echo "🧬 Starting $AGENT_COUNT OpenClaw Agents for Darwin Arena"
echo "================================================"
echo ""

# 检查OpenClaw是否安装
if ! command -v openclaw &> /dev/null; then
    echo "❌ OpenClaw not found. Please install OpenClaw first."
    exit 1
fi

# 创建临时目录
TEMP_DIR="/tmp/darwin-openclaw-agents"
mkdir -p "$TEMP_DIR"

# 为每个agent创建启动脚本
for i in $(seq 1 $AGENT_COUNT); do
    AGENT_ID="OpenClaw_Agent_$(printf "%03d" $i)"
    SCRIPT_FILE="$TEMP_DIR/agent_${i}.sh"

    cat > "$SCRIPT_FILE" << EOF
#!/bin/bash
# Auto-generated script for $AGENT_ID

echo "🤖 Starting $AGENT_ID..."

# 启动OpenClaw并自动执行命令
openclaw << 'COMMANDS'
/skill https://www.darwinx.fun/skill/darwin-trader.md
darwin_trader(command="connect", agent_id="$AGENT_ID", arena_url="$ARENA_URL")

# 进入自动交易循环
while true; do
    # 每30秒分析一次市场
    sleep 30
    darwin_trader(command="analyze")

    # 让LLM决定是否交易
    # (这里需要OpenClaw的LLM自主决策)
done
COMMANDS
EOF

    chmod +x "$SCRIPT_FILE"

    # 在后台启动
    echo "🚀 Launching $AGENT_ID..."
    nohup "$SCRIPT_FILE" > "$TEMP_DIR/agent_${i}.log" 2>&1 &

    echo "   PID: $!"
    echo "   Log: $TEMP_DIR/agent_${i}.log"
    echo ""

    # 避免同时启动太多
    sleep 2
done

echo "================================================"
echo "✅ All agents started!"
echo ""
echo "📊 Monitor logs:"
echo "   tail -f $TEMP_DIR/agent_*.log"
echo ""
echo "🛑 Stop all agents:"
echo "   pkill -f 'openclaw.*darwin'"
echo ""
