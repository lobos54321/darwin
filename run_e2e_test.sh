#!/bin/bash
# Darwin Arena E2E Test - Quick Start
# 快速启动完整的E2E测试环境

set -e

echo "🧬 Darwin Arena E2E Test - Quick Start"
echo "======================================"
echo ""

# 检查当前目录
if [ ! -f "arena_server/main.py" ]; then
    echo "❌ Error: Please run this script from the darwin project root directory"
    exit 1
fi

# 1. 检查依赖
echo "1️⃣  Checking dependencies..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 is not installed"
    exit 1
fi

if ! python3 -c "import aiohttp" 2>/dev/null; then
    echo "⚠️  aiohttp not found, installing..."
    pip3 install aiohttp
fi

echo "✅ Dependencies OK"
echo ""

# 2. 创建必要的目录
echo "2️⃣  Setting up directories..."
mkdir -p logs
mkdir -p data
echo "✅ Directories created"
echo ""

# 3. 启动服务器
echo "3️⃣  Starting Darwin Arena server..."
echo "   Server will run on http://localhost:8000"
echo "   Logs: logs/server.log"
echo ""

cd arena_server
python3 main.py > ../logs/server.log 2>&1 &
SERVER_PID=$!
cd ..

echo "   Server PID: $SERVER_PID"
echo "   Waiting for server to start..."
sleep 5

# 检查服务器是否启动
if ps -p $SERVER_PID > /dev/null; then
    echo "✅ Server started successfully"
else
    echo "❌ Server failed to start. Check logs/server.log"
    exit 1
fi
echo ""

# 4. 运行E2E测试
echo "4️⃣  Running E2E tests..."
echo "   This will take approximately 5-10 minutes"
echo "   Testing: Connection → Trades → Council → Hive Mind → Hot Updates → Champion"
echo ""

python3 test_e2e_production.py ws://localhost:8000

TEST_EXIT_CODE=$?

echo ""
echo "======================================"
echo "Test completed with exit code: $TEST_EXIT_CODE"
echo "======================================"
echo ""

# 5. 清理
echo "5️⃣  Cleanup..."
echo "   Stopping server (PID: $SERVER_PID)..."
kill $SERVER_PID 2>/dev/null || true

# 等待服务器停止
sleep 2

if ps -p $SERVER_PID > /dev/null 2>&1; then
    echo "   Force killing server..."
    kill -9 $SERVER_PID 2>/dev/null || true
fi

echo "✅ Cleanup complete"
echo ""

# 6. 显示结果
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "🎉 E2E Test PASSED!"
    echo ""
    echo "Next steps:"
    echo "  1. Review the test results above"
    echo "  2. Check logs/server.log for server logs"
    echo "  3. Deploy to production: zeabur deploy"
    echo ""
else
    echo "❌ E2E Test FAILED"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check logs/server.log for errors"
    echo "  2. Review the test output above"
    echo "  3. Run individual tests manually"
    echo ""
fi

exit $TEST_EXIT_CODE
