#!/usr/bin/env python3
"""
Darwin Arena - OpenClaw Agent Swarm Launcher

启动多个OpenClaw agents参与Darwin Arena交易竞赛
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加darwin_trader到路径
SKILL_DIR = Path(__file__).parent / "skill-package" / "darwin-trader"
sys.path.insert(0, str(SKILL_DIR))

from darwin_trader import (
    darwin_connect,
    darwin_fetch_prices,
    darwin_analyze,
    darwin_trade,
    darwin_status,
    darwin_disconnect
)

class OpenClawAgent:
    """模拟OpenClaw Agent的自主交易逻辑"""

    def __init__(self, agent_id: str, arena_url: str = "wss://www.darwinx.fun"):
        self.agent_id = agent_id
        self.arena_url = arena_url
        self.running = False

    async def start(self):
        """启动agent"""
        print(f"🤖 Starting {self.agent_id}...")

        # 连接到arena
        result = await darwin_connect(self.agent_id, self.arena_url)
        if result["status"] != "connected":
            print(f"❌ {self.agent_id} failed to connect: {result['message']}")
            return

        print(f"✅ {self.agent_id} connected!")
        print(f"   {result['message']}")

        self.running = True

        # 开始交易循环
        await self.trading_loop()

    async def trading_loop(self):
        """主交易循环"""
        cycle = 0

        while self.running:
            try:
                cycle += 1
                print(f"\n🔄 {self.agent_id} - Cycle {cycle}")

                # 1. 获取价格
                prices_result = await darwin_fetch_prices()
                if prices_result["status"] != "success":
                    print(f"⚠️ Failed to fetch prices: {prices_result['message']}")
                    await asyncio.sleep(30)
                    continue

                # 2. 分析市场
                analysis = await darwin_analyze(prices_result["prices"])
                if analysis["status"] != "success":
                    print(f"⚠️ Analysis failed: {analysis['message']}")
                    await asyncio.sleep(30)
                    continue

                # 3. 简单的交易策略（这里应该用LLM，但我们先用规则）
                await self.simple_strategy(analysis)

                # 4. 查看状态
                status = await darwin_status()
                if status["status"] == "success":
                    print(f"💰 {self.agent_id} Status:")
                    print(f"   Balance: ${status['balance']:.2f}")
                    print(f"   Total Value: ${status['total_value']:.2f}")
                    print(f"   PnL: ${status['total_pnl']:.2f} ({status['total_pnl_pct']:+.2f}%)")

                # 等待下一个周期
                await asyncio.sleep(30)

            except Exception as e:
                print(f"❌ {self.agent_id} error: {e}")
                await asyncio.sleep(30)

    async def simple_strategy(self, analysis):
        """
        简单的交易策略（演示用）

        真正的OpenClaw会用LLM来做这个决策！
        """
        tokens = analysis["tokens"]
        balance = analysis["portfolio"]["balance"]
        positions = analysis["portfolio"]["positions"]

        # 策略1: 买入超卖的代币
        for token in tokens:
            if token["signal"] == "OVERSOLD" and token["signal_strength"] == "STRONG":
                # 检查是否有足够余额
                if balance > 100:
                    print(f"💡 {self.agent_id} Strategy: BUY {token['symbol']} (oversold)")
                    result = await darwin_trade(
                        action="buy",
                        symbol=token["symbol"],
                        amount=100,
                        reason="oversold_signal"
                    )
                    if result["status"] == "success":
                        print(f"   ✅ {result['message']}")
                    else:
                        print(f"   ❌ {result['message']}")
                    return  # 每次只交易一个

        # 策略2: 卖出超买的持仓
        for token in tokens:
            if token["signal"] == "OVERBOUGHT" and token["position"] > 0:
                print(f"💡 {self.agent_id} Strategy: SELL {token['symbol']} (overbought)")
                result = await darwin_trade(
                    action="sell",
                    symbol=token["symbol"],
                    amount=token["position"],
                    reason="overbought_signal"
                )
                if result["status"] == "success":
                    print(f"   ✅ {result['message']}")
                else:
                    print(f"   ❌ {result['message']}")
                return

    async def stop(self):
        """停止agent"""
        self.running = False
        await darwin_disconnect()
        print(f"🛑 {self.agent_id} stopped")


async def launch_swarm(agent_count: int, arena_url: str):
    """启动agent群"""
    print(f"🧬 Launching {agent_count} OpenClaw Agents")
    print(f"🎯 Target Arena: {arena_url}")
    print("=" * 50)
    print()

    agents = []

    # 创建agents
    for i in range(1, agent_count + 1):
        agent_id = f"OpenClaw_Agent_{i:03d}"
        agent = OpenClawAgent(agent_id, arena_url)
        agents.append(agent)

    # 启动所有agents
    tasks = [agent.start() for agent in agents]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping all agents...")
        for agent in agents:
            await agent.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Launch OpenClaw Agent Swarm for Darwin Arena")
    parser.add_argument("--count", type=int, default=3, help="Number of agents to launch (default: 3)")
    parser.add_argument("--arena", type=str, default="wss://www.darwinx.fun", help="Arena WebSocket URL")

    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║        🧬 Darwin Arena - OpenClaw Agent Swarm 🧬         ║
║                                                          ║
║  This script simulates multiple OpenClaw agents          ║
║  trading autonomously in Darwin Arena.                   ║
║                                                          ║
║  In real usage, each OpenClaw instance would use         ║
║  its LLM to make trading decisions.                      ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
    """)

    asyncio.run(launch_swarm(args.count, args.arena))
