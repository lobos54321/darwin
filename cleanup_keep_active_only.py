#!/usr/bin/env python3
"""
只保留真正在线的OpenClaw Agent和Bot
"""
import requests
import json

ARENA_URL = "https://www.darwinx.fun"

def cleanup_inactive(dry_run=True):
    """删除所有不活跃的Agent，只保留Bot和真正在线的"""

    # 获取所有Agent
    response = requests.get(f"{ARENA_URL}/leaderboard")
    agents = response.json().get("rankings", [])

    # 获取统计信息
    stats = requests.get(f"{ARENA_URL}/stats").json()
    connected_count = stats.get("connected_agents", 0)

    print(f"📊 Total agents: {len(agents)}")
    print(f"🔌 Connected agents: {connected_count}")
    print(f"\n🔍 Analyzing agents...\n")

    # 保护的Bot账户
    protected_bots = ["Bot_Alpha", "Bot_Beta", "Bot_Gamma", "ClawdBot_Test"]

    to_keep = []
    to_delete = []

    for agent in agents:
        agent_id = agent["agent_id"]
        pnl = agent["pnl_percent"]

        # 保留Bot
        if agent_id in protected_bots:
            to_keep.append(agent_id)
            print(f"🤖 Keep Bot: {agent_id} (PnL: {pnl:+.2f}%)")
        # 保留有正PnL的Agent（说明最近有成功交易）
        elif pnl > 0.1:
            to_keep.append(agent_id)
            print(f"✅ Keep Active: {agent_id} (PnL: {pnl:+.2f}%)")
        # 删除其他所有
        else:
            to_delete.append(agent_id)
            print(f"🗑️  Delete: {agent_id} (PnL: {pnl:+.2f}%)")

    print(f"\n📊 Summary:")
    print(f"   Keep: {len(to_keep)} agents")
    print(f"   Delete: {len(to_delete)} agents")

    if dry_run:
        print(f"\n⚠️  DRY RUN - No agents deleted")
        print(f"   Run with --execute to actually delete")
        return

    # 实际删除
    print(f"\n🗑️  Deleting {len(to_delete)} agents...")

    try:
        response = requests.post(
            f"{ARENA_URL}/admin/remove-agents",
            json=to_delete,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ Successfully deleted {len(result['removed'])} agents")
            print(f"   Remaining: {result.get('remaining', [])}")
        else:
            print(f"\n❌ Failed: {response.status_code}")
            print(f"   {response.text}")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    import sys
    dry_run = "--execute" not in sys.argv
    cleanup_inactive(dry_run=dry_run)
