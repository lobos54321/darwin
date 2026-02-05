"""
测试 Gelato 自动发币
模拟一个 Agent 升天，触发 Gelato Relay 发币
"""

import asyncio
import os
import sys

# 加载环境变量
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 读取 .env
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

from gelato_relay import GelatoRelayer
from chain import ChainIntegration

async def test_gelato():
    print("=" * 60)
    print("🧪 Testing Gelato Relay Token Launch")
    print("=" * 60)
    
    api_key = os.getenv("GELATO_API_KEY")
    print(f"\n📋 Config:")
    print(f"   GELATO_API_KEY: {api_key[:10]}..." if api_key else "   ❌ GELATO_API_KEY not set")
    print(f"   FACTORY: {os.getenv('DARWIN_FACTORY_ADDRESS', 'not set')}")
    
    if not api_key:
        print("\n❌ Please set GELATO_API_KEY in .env")
        return
    
    # 测试 Gelato Relayer
    print("\n🔄 Testing Gelato Relayer...")
    relayer = GelatoRelayer()
    
    # 模拟发币
    agent_id = "TestChampion_001"
    epoch = 1
    owner = os.getenv("DARWIN_PLATFORM_WALLET", "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9")
    strategy = "def trade(): return 'BUY'"
    
    print(f"\n🚀 Launching token:")
    print(f"   Agent: {agent_id}")
    print(f"   Epoch: {epoch}")
    print(f"   Owner: {owner}")
    
    result = await relayer.launch_token(
        agent_id=agent_id,
        epoch=epoch,
        owner_address=owner,
        strategy_code=strategy
    )
    
    if result:
        print(f"\n✅ Gelato task created!")
        print(f"   Task ID: {result.task_id}")
        print(f"   Status: {result.status}")
        
        # 等待几秒后检查状态
        print("\n⏳ Waiting 10 seconds for confirmation...")
        await asyncio.sleep(10)
        
        status = await relayer.check_task_status(result.task_id)
        if status:
            print(f"\n📊 Task Status:")
            print(f"   Status: {status.status}")
            print(f"   TX Hash: {status.tx_hash or 'pending'}")
            
            if status.tx_hash:
                print(f"\n🔗 View on Basescan:")
                print(f"   https://sepolia.basescan.org/tx/{status.tx_hash}")
    else:
        print("\n❌ Gelato launch failed")
        print("   Check if Gas Tank has funds and API key is correct")

if __name__ == "__main__":
    asyncio.run(test_gelato())
