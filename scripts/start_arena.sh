#!/bin/bash
# 启动 Arena Server

cd "$(dirname "$0")/../arena_server"

echo "🧬 Starting Project Darwin Arena Server..."
echo ""

# 检查依赖
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "Installing dependencies..."
    pip3 install fastapi uvicorn aiohttp websockets
fi

# 启动服务器
python3 -m uvicorn main:app --host 0.0.0.0 --port 8888 --reload
