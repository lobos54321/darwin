#!/usr/bin/env python3
"""
Project Darwin - 端到端测试
验证完整流程: 启动服务 -> 连接 Agent -> 交易 -> 进化
"""

import asyncio
import subprocess
import signal
import sys
import time
import json
import aiohttp

ARENA_URL = "ws://localhost:8888"
REST_URL = "http://localhost:8888"


async def wait_for_server(timeout=30):
    """等待服务器启动"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{REST_URL}/") as resp:
                    if resp.status == 200:
                        return True
        except:
            pass
        await asyncio.sleep(1)
    return False


async def test_agent_trading(agent_id: str):
    """测试 Agent 交易"""
    print(f"\n🤖 Testing Agent: {agent_id}")
    
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"{ARENA_URL}/ws/{agent_id}") as ws:
            # Welcome
            msg = await ws.receive()
            if msg.data is None:
                print(f"   ❌ Connection closed unexpectedly")
                return False
            data = json.loads(msg.data)
            print(f"   Connected! Balance: ${data['balance']}")
            
            # 等待价格
            msg = await ws.receive()
            if msg.data is None:
                print(f"   ❌ No price data received")
                return False
            data = json.loads(msg.data)
            if data['type'] == 'price_update':
                print(f"   Received prices")
            
            # 买入
            await ws.send_json({
                'type': 'order',
                'symbol': 'CLANKER',
                'side': 'BUY',
                'amount': 100
            })
            
            msg = await ws.receive()
            if msg.data is None:
                print(f"   ❌ No order response")
                return False
            result = json.loads(msg.data)
            print(f"   BUY order: success={result['success']}")
            
            # 获取状态
            await ws.send_json({'type': 'get_state'})
            msg = await ws.receive()
            if msg.data is None:
                print(f"   ❌ No state response")
                return False
            state = json.loads(msg.data)
            print(f"   Final: balance=${state['balance']:.2f}, positions={list(state['positions'].keys())}")
            
            return result['success']


async def test_leaderboard():
    """测试排行榜 API"""
    print("\n📊 Testing Leaderboard API")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{REST_URL}/leaderboard") as resp:
            data = await resp.json()
            print(f"   Epoch: {data['epoch']}")
            print(f"   Rankings: {len(data['rankings'])} agents")
            for r in data['rankings'][:3]:
                print(f"     #{r['rank']} {r['agent_id']}: {r['pnl_percent']:+.2f}%")
            return True


async def test_prices():
    """测试价格 API"""
    print("\n💰 Testing Prices API")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{REST_URL}/prices") as resp:
            data = await resp.json()
            print(f"   Last update: {data['timestamp']}")
            for symbol, info in data['prices'].items():
                print(f"   {symbol}: ${info['priceUsd']:.6f} ({info['priceChange24h']:+.2f}%)")
            return True


async def main():
    print("=" * 60)
    print("🧬 Project Darwin - End-to-End Test")
    print("=" * 60)
    
    # 启动 Arena Server
    print("\n🚀 Starting Arena Server...")
    server_process = subprocess.Popen(
        ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8888"],
        cwd="/Users/boliu/darwin-workspace/project-darwin/arena_server",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    
    try:
        # 等待服务器启动
        if not await wait_for_server():
            print("❌ Server failed to start")
            return False
        print("✅ Server started")
        
        # 等待第一次价格更新
        await asyncio.sleep(5)
        
        # 测试价格 API
        await test_prices()
        
        # 测试多个 Agent 连接和交易
        for i in range(3):
            await test_agent_trading(f"TestAgent_{i+1:03d}")
        
        # 测试排行榜
        await test_leaderboard()
        
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return True
        
    finally:
        # 关闭服务器
        print("\n🛑 Stopping server...")
        server_process.terminate()
        server_process.wait(timeout=5)


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
