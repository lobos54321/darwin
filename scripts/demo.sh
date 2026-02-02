#!/bin/bash

# Project Darwin - Quick Demo Script
# 一键启动演示

set -e

echo "🧬 ==========================================="
echo "   Project Darwin - AI Agent Arena"
echo "   一键演示脚本"
echo "🧬 ==========================================="
echo ""

cd "$(dirname "$0")/.."

# 检查 Python 依赖
echo "📦 Checking dependencies..."
pip3 install -q -r requirements.txt 2>/dev/null || true

# 启动服务器
echo ""
echo "🚀 Starting Arena Server..."
cd arena_server
python3 -m uvicorn main:app --host 0.0.0.0 --port 8888 &
SERVER_PID=$!
cd ..

# 等待服务器启动
echo "⏳ Waiting for server to start..."
sleep 5

# 检查服务器状态
if curl -s http://localhost:8888/health > /dev/null 2>&1; then
    echo "✅ Server is running!"
else
    echo "❌ Server failed to start"
    kill $SERVER_PID 2>/dev/null
    exit 1
fi

echo ""
echo "🎮 ==========================================="
echo "   Arena Server is LIVE!"
echo "🎮 ==========================================="
echo ""
echo "📊 Live Dashboard:  http://localhost:8888/live"
echo "🔌 API Endpoint:    http://localhost:8888/"
echo "📈 Leaderboard:     http://localhost:8888/leaderboard"
echo "💰 Prices:          http://localhost:8888/prices"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# 打开浏览器 (macOS)
if command -v open &> /dev/null; then
    open http://localhost:8888/live
fi

# 等待用户中断
trap "echo ''; echo '🛑 Stopping server...'; kill $SERVER_PID 2>/dev/null; exit 0" INT
wait $SERVER_PID
