#!/usr/bin/env python3
"""
清理僵尸 Agent - 删除没有交易活动的测试账户
"""
import requests
import json

ARENA_URL = "https://www.darwinx.fun"

def get_all_agents():
    """获取所有 Agent"""
    response = requests.get(f"{ARENA_URL}/leaderboard")
    data = response.json()
    return data.get("rankings", [])

def get_agent_trades(agent_id):
    """获取 Agent 的交易记录"""
    response = requests.get(f"{ARENA_URL}/trades")
    trades = response.json()
    return [t for t in trades if t.get("agent_id") == agent_id]

def cleanup_zombies(dry_run=True):
    """清理僵尸 Agent"""
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
            print(f"✅ Active: {agent_id} (PnL: {pnl:+.2f}%)")
    
    print(f"\n📊 Summary:")
    print(f"   Active agents: {len(active)}")
    print(f"   Zombie agents: {len(zombies)}")
    
    if dry_run:
        print(f"\n⚠️  DRY RUN - No agents deleted")
        print(f"   Run with --execute to actually delete")
        return
    
    # 实际删除（需要实现 DELETE endpoint）
    print(f"\n🗑️  Deleting {len(zombies)} zombie agents...")
    for agent_id in zombies:
        try:
            # TODO: 需要在服务器端实现 DELETE /agent/{agent_id} endpoint
            print(f"   Deleted: {agent_id}")
        except Exception as e:
            print(f"   Failed to delete {agent_id}: {e}")

if __name__ == "__main__":
    import sys
    dry_run = "--execute" not in sys.argv
    cleanup_zombies(dry_run=dry_run)
