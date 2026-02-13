#!/usr/bin/env python3
"""
通过Admin API清理僵尸Agent
"""
import requests
import json

ARENA_URL = "https://www.darwinx.fun"

def get_all_agents():
    """获取所有Agent"""
    response = requests.get(f"{ARENA_URL}/leaderboard")
    data = response.json()
    return data.get("rankings", [])

def cleanup_zombies(dry_run=True):
    """清理僵尸Agent"""
    agents = get_all_agents()

    print(f"📊 Total agents: {len(agents)}")
    print(f"🔍 Scanning for zombies...\n")

    zombies = []
    active = []

    for agent in agents:
        agent_id = agent["agent_id"]
        pnl = agent["pnl_percent"]
        total_value = agent["total_value"]

        # 僵尸条件：PnL = 0% 且余额 = 1000（初始值）
        is_zombie = (abs(pnl) < 0.0001 and abs(total_value - 1000) < 0.01)

        if is_zombie:
            zombies.append(agent_id)
            print(f"💀 Zombie: {agent_id}")
        else:
            active.append(agent_id)
            print(f"✅ Active: {agent_id} (PnL: {pnl:+.2f}%, Value: ${total_value:.2f})")

    print(f"\n📊 Summary:")
    print(f"   Active agents: {len(active)}")
    print(f"   Zombie agents: {len(zombies)}")

    if dry_run:
        print(f"\n⚠️  DRY RUN - No agents deleted")
        print(f"   Run with --execute to actually delete")
        return

    # 实际删除
    print(f"\n🗑️  Deleting {len(zombies)} zombie agents...")

    try:
        response = requests.post(
            f"{ARENA_URL}/admin/remove-agents",
            json=zombies,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ Successfully deleted {len(result['removed'])} agents")
            print(f"   Remaining agents: {result.get('remaining', [])}")
        else:
            print(f"\n❌ Failed: {response.status_code}")
            print(f"   {response.text}")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    import sys
    dry_run = "--execute" not in sys.argv
    cleanup_zombies(dry_run=dry_run)
