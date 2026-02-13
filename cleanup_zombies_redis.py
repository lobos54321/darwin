#!/usr/bin/env python3
"""
直接通过Redis清理僵尸Agent
"""
import redis
import json
import os

# Redis配置
REDIS_HOST = os.getenv("REDIS_HOST", "sfo1.clusters.zeabur.com")
REDIS_PORT = int(os.getenv("REDIS_PORT", "31441"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# Redis Keys
KEY_API_KEYS = "darwin:api_keys"
KEY_AGENTS = "darwin:agents"

def cleanup_zombies(dry_run=True):
    """清理僵尸Agent"""

    # 连接Redis
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True
    )

    print("🔌 Connected to Redis")

    # 获取所有agents
    agents_data = r.hgetall(KEY_AGENTS)
    print(f"📊 Total agents in Redis: {len(agents_data)}")

    zombies = []
    active = []

    for agent_id, agent_json in agents_data.items():
        agent = json.loads(agent_json)
        balance = agent.get("balance", 1000)
        positions = agent.get("positions", {})
        pnl_percent = agent.get("pnl_percent", 0)

        # 僵尸条件：余额=1000，无持仓，PnL=0
        is_zombie = (
            abs(balance - 1000) < 0.01 and
            len(positions) == 0 and
            abs(pnl_percent) < 0.0001
        )

        if is_zombie:
            zombies.append(agent_id)
            print(f"💀 Zombie: {agent_id}")
        else:
            active.append(agent_id)
            print(f"✅ Active: {agent_id} (Balance: ${balance:.2f}, PnL: {pnl_percent:+.2f}%)")

    print(f"\n📊 Summary:")
    print(f"   Active agents: {len(active)}")
    print(f"   Zombie agents: {len(zombies)}")

    if dry_run:
        print(f"\n⚠️  DRY RUN - No agents deleted")
        print(f"   Run with --execute to actually delete")
        return

    # 实际删除
    print(f"\n🗑️  Deleting {len(zombies)} zombie agents...")

    api_keys_data = r.hgetall(KEY_API_KEYS)

    for agent_id in zombies:
        try:
            # 1. 从agents hash删除
            r.hdel(KEY_AGENTS, agent_id)

            # 2. 从api_keys hash删除对应的key
            keys_to_delete = [k for k, v in api_keys_data.items() if v == agent_id]
            if keys_to_delete:
                r.hdel(KEY_API_KEYS, *keys_to_delete)

            print(f"   ✅ Deleted: {agent_id}")
        except Exception as e:
            print(f"   ❌ Failed to delete {agent_id}: {e}")

    print(f"\n✅ Cleanup complete!")

if __name__ == "__main__":
    import sys
    dry_run = "--execute" not in sys.argv
    cleanup_zombies(dry_run=dry_run)
