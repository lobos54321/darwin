"""
链上集成模块
负责与 Base 链智能合约交互
"""

import os
import json
import hashlib
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

# Web3 配置
BASE_SEPOLIA_RPC = os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
BASE_MAINNET_RPC = os.getenv("BASE_MAINNET_RPC", "https://mainnet.base.org")
PRIVATE_KEY = os.getenv("DARWIN_PRIVATE_KEY", "")

# 合约地址 (Base Sepolia - 2026-02-02 部署)
FACTORY_ADDRESS = os.getenv("DARWIN_FACTORY_ADDRESS", "0x63685E3Ff986Ae389496C08b6c18F30EBdb9fa71")
PLATFORM_WALLET = os.getenv("DARWIN_PLATFORM_WALLET", "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9")


@dataclass
class TokenLaunchRecord:
    """代币发行记录"""
    agent_id: str
    epoch: int
    token_address: str
    strategy_hash: str
    owner_address: str
    launched_at: datetime
    tx_hash: str


class ChainIntegration:
    """Base 链集成"""
    
    def __init__(self, testnet: bool = True):
        self.testnet = testnet
        self.rpc_url = BASE_SEPOLIA_RPC if testnet else BASE_MAINNET_RPC
        self.launches: list[TokenLaunchRecord] = []
        self._web3 = None
    
    @property
    def web3(self):
        """懒加载 Web3"""
        if self._web3 is None:
            try:
                from web3 import Web3
                self._web3 = Web3(Web3.HTTPProvider(self.rpc_url))
                if self._web3.is_connected():
                    print(f"🔗 Connected to Base {'Sepolia' if self.testnet else 'Mainnet'}")
                else:
                    print("❌ Failed to connect to Base chain")
            except ImportError:
                print("⚠️  web3 not installed. Run: pip install web3")
                return None
        return self._web3
    
    def compute_strategy_hash(self, strategy_code: str) -> str:
        """计算策略代码哈希"""
        return "0x" + hashlib.sha256(strategy_code.encode()).hexdigest()
    
    async def prepare_token_launch(
        self,
        agent_id: str,
        epoch: int,
        owner_address: str,
        strategy_code: str
    ) -> dict:
        """
        准备代币发行 (不实际发送交易)
        返回发行所需的参数
        """
        strategy_hash = self.compute_strategy_hash(strategy_code)
        
        return {
            "agent_id": agent_id,
            "epoch": epoch,
            "owner_address": owner_address,
            "strategy_hash": strategy_hash,
            "factory_address": FACTORY_ADDRESS,
            "network": "base-sepolia" if self.testnet else "base",
            "ready": bool(FACTORY_ADDRESS and owner_address),
            "estimated_gas": 2000000,  # 估算
        }
    
    async def launch_token(
        self,
        agent_id: str,
        epoch: int,
        owner_address: str,
        strategy_code: str
    ) -> Optional[TokenLaunchRecord]:
        """
        实际发行代币 (需要 PRIVATE_KEY)
        """
        if not self.web3:
            print("❌ Web3 not available")
            return None
        
        if not FACTORY_ADDRESS:
            print("❌ Factory address not configured")
            return None
        
        if not PRIVATE_KEY:
            print("❌ Private key not configured")
            return None
        
        strategy_hash = self.compute_strategy_hash(strategy_code)
        
        # 加载合约 ABI
        # TODO: 从编译后的 artifacts 加载
        factory_abi = [
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
        
        try:
            # 获取账户
            from web3 import Account
            account = Account.from_key(PRIVATE_KEY)
            
            # 加载合约
            factory = self.web3.eth.contract(
                address=self.web3.to_checksum_address(FACTORY_ADDRESS),
                abi=factory_abi
            )
            
            # 构建交易
            tx = factory.functions.launchToken(
                agent_id,
                epoch,
                self.web3.to_checksum_address(owner_address),
                bytes.fromhex(strategy_hash[2:])
            ).build_transaction({
                "from": account.address,
                "nonce": self.web3.eth.get_transaction_count(account.address),
                "gas": 2000000,
                "gasPrice": self.web3.eth.gas_price
            })
            
            # 签名并发送
            signed_tx = self.web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # 等待确认
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                # 从事件中获取代币地址
                # TODO: 解析 TokenLaunched 事件
                token_address = "0x..."  # 需要从事件解析
                
                record = TokenLaunchRecord(
                    agent_id=agent_id,
                    epoch=epoch,
                    token_address=token_address,
                    strategy_hash=strategy_hash,
                    owner_address=owner_address,
                    launched_at=datetime.now(),
                    tx_hash=tx_hash.hex()
                )
                
                self.launches.append(record)
                print(f"🚀 Token launched! TX: {tx_hash.hex()}")
                
                return record
            else:
                print(f"❌ Transaction failed: {tx_hash.hex()}")
                return None
                
        except Exception as e:
            print(f"❌ Launch error: {e}")
            return None
    
    def get_launch_history(self) -> list[TokenLaunchRecord]:
        """获取发行历史"""
        return self.launches


# 冠军候选追踪
class AscensionTracker:
    """
    追踪哪些 Agent 有资格发币
    条件: 连续 3 个 Epoch 第一，或总收益率超过 500%
    """
    
    def __init__(self):
        self.consecutive_wins: dict[str, int] = {}  # agent_id -> 连续获胜次数
        self.total_returns: dict[str, float] = {}   # agent_id -> 总收益率
        self.ascended: set[str] = set()             # 已升天的 Agent
    
    def record_epoch_result(self, rankings: list[tuple]) -> Optional[str]:
        """
        记录 Epoch 结果，返回应该发币的 Agent (如果有)
        
        Args:
            rankings: [(agent_id, pnl_percent, total_value), ...]
        
        Returns:
            应该发币的 agent_id，或 None
        """
        if not rankings:
            return None
        
        winner_id = rankings[0][0]
        winner_pnl = rankings[0][1]
        
        # 更新连续获胜
        for agent_id in list(self.consecutive_wins.keys()):
            if agent_id != winner_id:
                self.consecutive_wins[agent_id] = 0
        
        self.consecutive_wins[winner_id] = self.consecutive_wins.get(winner_id, 0) + 1
        
        # 更新总收益率
        for agent_id, pnl, _ in rankings:
            self.total_returns[agent_id] = self.total_returns.get(agent_id, 0) + pnl
        
        # 检查升天条件
        candidate = None
        
        # 条件1: 连续 3 次获胜
        if self.consecutive_wins.get(winner_id, 0) >= 3:
            if winner_id not in self.ascended:
                candidate = winner_id
        
        # 条件2: 总收益率超过 500%
        for agent_id, total_return in self.total_returns.items():
            if total_return >= 500 and agent_id not in self.ascended:
                candidate = agent_id
                break
        
        if candidate:
            self.ascended.add(candidate)
            print(f"🌟 {candidate} has achieved ASCENSION!")
        
        return candidate
    
    def get_stats(self, agent_id: str) -> dict:
        """获取 Agent 的升天进度"""
        return {
            "consecutive_wins": self.consecutive_wins.get(agent_id, 0),
            "total_return": self.total_returns.get(agent_id, 0),
            "ascended": agent_id in self.ascended,
            "progress_wins": f"{self.consecutive_wins.get(agent_id, 0)}/3",
            "progress_return": f"{self.total_returns.get(agent_id, 0):.1f}%/500%"
        }


# 测试
if __name__ == "__main__":
    import asyncio
    
    async def test():
        print("=== Chain Integration Test ===")
        
        chain = ChainIntegration(testnet=True)
        print(f"RPC: {chain.rpc_url}")
        
        # 测试策略哈希
        code = "def on_price_update(prices): return 'BUY'"
        hash_val = chain.compute_strategy_hash(code)
        print(f"Strategy hash: {hash_val}")
        
        # 测试准备发行
        params = await chain.prepare_token_launch(
            agent_id="TestAgent",
            epoch=1,
            owner_address="0x1234567890123456789012345678901234567890",
            strategy_code=code
        )
        print(f"Launch params: {json.dumps(params, indent=2)}")
        
        # 测试升天追踪
        tracker = AscensionTracker()
        
        # 模拟 3 轮比赛
        for i in range(3):
            rankings = [
                ("Agent_001", 10.0 + i*5, 1100 + i*50),
                ("Agent_002", 5.0, 1050),
            ]
            candidate = tracker.record_epoch_result(rankings)
            print(f"Epoch {i+1}: Winner=Agent_001, Candidate={candidate}")
        
        stats = tracker.get_stats("Agent_001")
        print(f"Agent_001 stats: {stats}")
        
        print("\n✅ Chain integration module OK")
    
    asyncio.run(test())
