"""
Gelato Relay 集成
无需私钥，安全的自动发币

使用方法:
1. 注册 Gelato: https://relay.gelato.network
2. 创建 Sponsor API Key
3. 存入测试 ETH 到 Gas Tank
4. 配置 GELATO_API_KEY 环境变量
"""

import os
import json
import hashlib
import aiohttp
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

# Gelato Relay API
GELATO_RELAY_URL = "https://relay.gelato.digital"

# 配置
GELATO_API_KEY = os.getenv("GELATO_API_KEY", "")
BASE_SEPOLIA_CHAIN_ID = 84532
FACTORY_ADDRESS = os.getenv("DARWIN_FACTORY_ADDRESS", "0x63685E3Ff986Ae389496C08b6c18F30EBdb9fa71")

# Factory ABI (只需要 launchToken)
FACTORY_ABI = [
    {
        "inputs": [
            {"name": "agentId", "type": "string"},
            {"name": "epoch", "type": "uint256"},
            {"name": "agentOwner", "type": "address"},
            {"name": "strategyHash", "type": "bytes32"}
        ],
        "name": "launchToken",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]


@dataclass
class GelatoTaskResult:
    """Gelato 任务结果"""
    task_id: str
    status: str
    tx_hash: Optional[str] = None
    token_address: Optional[str] = None


class GelatoRelayer:
    """Gelato Relay 封装 - 无需私钥的安全发币"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or GELATO_API_KEY
        if not self.api_key:
            print("⚠️  GELATO_API_KEY not configured. Get one at https://relay.gelato.network")
    
    def compute_strategy_hash(self, strategy_code: str) -> str:
        """计算策略代码哈希"""
        return "0x" + hashlib.sha256(strategy_code.encode()).hexdigest()
    
    def encode_launch_token(
        self,
        agent_id: str,
        epoch: int,
        owner_address: str,
        strategy_hash: str
    ) -> str:
        """编码 launchToken 调用数据"""
        try:
            from eth_abi import encode
            from eth_utils import function_signature_to_4byte_selector
            
            # 函数选择器
            selector = function_signature_to_4byte_selector("launchToken(string,uint256,address,bytes32)")
            
            # 编码参数
            encoded_args = encode(
                ["string", "uint256", "address", "bytes32"],
                [agent_id, epoch, owner_address, bytes.fromhex(strategy_hash[2:])]
            )
            
            return "0x" + selector.hex() + encoded_args.hex()
            
        except ImportError:
            # 如果没有 eth_abi，用 web3
            from web3 import Web3
            w3 = Web3()
            contract = w3.eth.contract(abi=FACTORY_ABI)
            return contract.encode_abi(
                "launchToken",
                [agent_id, epoch, owner_address, bytes.fromhex(strategy_hash[2:])]
            )
    
    async def launch_token(
        self,
        agent_id: str,
        epoch: int,
        owner_address: str,
        strategy_code: str
    ) -> Optional[GelatoTaskResult]:
        """
        通过 Gelato Relay 发币
        
        ✅ 无需私钥
        ✅ Gelato 管理安全
        ✅ 从 Gas Tank 支付 gas
        """
        if not self.api_key:
            print("❌ Gelato API key not configured")
            return None
        
        strategy_hash = self.compute_strategy_hash(strategy_code)
        
        # 编码调用数据
        call_data = self.encode_launch_token(
            agent_id, epoch, owner_address, strategy_hash
        )
        
        # 构建 Gelato Relay 请求
        request = {
            "chainId": BASE_SEPOLIA_CHAIN_ID,
            "target": FACTORY_ADDRESS,
            "data": call_data,
            "sponsorApiKey": self.api_key
        }
        
        print(f"🔄 Sending to Gelato Relay...")
        print(f"   Agent: {agent_id}")
        print(f"   Owner: {owner_address}")
        print(f"   Chain: Base Sepolia ({BASE_SEPOLIA_CHAIN_ID})")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{GELATO_RELAY_URL}/relays/v2/sponsored-call",
                    json=request,
                    headers={"Content-Type": "application/json"}
                ) as resp:
                    result = await resp.json()
                    
                    if resp.status == 200 or resp.status == 201:
                        task_id = result.get("taskId")
                        print(f"✅ Gelato task created: {task_id}")
                        
                        return GelatoTaskResult(
                            task_id=task_id,
                            status="pending"
                        )
                    else:
                        print(f"❌ Gelato error: {result}")
                        return None
                        
        except Exception as e:
            print(f"❌ Gelato request failed: {e}")
            return None
    
    async def check_task_status(self, task_id: str) -> Optional[GelatoTaskResult]:
        """检查 Gelato 任务状态"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{GELATO_RELAY_URL}/tasks/status/{task_id}"
                ) as resp:
                    result = await resp.json()
                    
                    task = result.get("task", {})
                    status = task.get("taskState", "unknown")
                    tx_hash = task.get("transactionHash")
                    
                    return GelatoTaskResult(
                        task_id=task_id,
                        status=status,
                        tx_hash=tx_hash
                    )
                    
        except Exception as e:
            print(f"❌ Status check failed: {e}")
            return None


# 测试
if __name__ == "__main__":
    import asyncio
    
    async def test():
        relayer = GelatoRelayer()
        
        if not relayer.api_key:
            print("\n⚠️  需要配置 GELATO_API_KEY")
            print("1. 访问 https://relay.gelato.network")
            print("2. 创建账户，获取 Sponsor API Key")
            print("3. 存入 Sepolia ETH 到 Gas Tank")
            print("4. export GELATO_API_KEY=你的key")
            return
        
        # 测试编码
        data = relayer.encode_launch_token(
            "TestAgent",
            1,
            "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9",
            "0x" + "01" * 32
        )
        print(f"Encoded data: {data[:50]}...")
        
        print("\n✅ Gelato Relayer ready!")
    
    asyncio.run(test())
