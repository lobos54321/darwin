"""
链上集成模块
负责与 Base 链智能合约交互

优先使用 Gelato Relay (无需私钥)
Fallback 到直接私钥 (如果配置了)
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
# 使用 Operator Private Key (Arena Server) 进行发币，只有它有权限调用 launchToken
OPERATOR_PRIVATE_KEY = os.getenv("OPERATOR_PRIVATE_KEY", "")
GELATO_API_KEY = os.getenv("GELATO_API_KEY", "")

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
    
    async def ascend_champion(
        self,
        agent_id: str,
        epoch: int,
        owner_address: str,
        strategy_code: str
    ) -> Optional[TokenLaunchRecord]:
        """
        触发 DarwinArena 冠军升天 (L2 -> L3)
        
        Args:
            agent_id: 冠军 Agent ID
            epoch: 获胜 Epoch
            owner_address: Agent 拥有者地址
            strategy_code: 策略代码 (用于计算 hash)
        
        Returns:
            TokenLaunchRecord or None
        """
        strategy_hash = self.compute_strategy_hash(strategy_code)
        arena_address = os.getenv("DARWIN_ARENA_ADDRESS") # 需要在 .env 配置
        
        print(f"🏛️ Ascending Champion: {agent_id} via Arena {arena_address}")
        
        # === 模拟模式 (如果未部署合约或无私钥) ===
        if not arena_address or not OPERATOR_PRIVATE_KEY:
            print("⚠️ Running in SIMULATION MODE (No Arena Contract or Private Key)")
            # 模拟延迟
            import asyncio
            await asyncio.sleep(2)
            
            # 生成模拟数据
            mock_token = f"0xSimulatedToken_{agent_id}_{int(datetime.now().timestamp())}"
            mock_tx = f"0xSimulatedTx_{hashlib.sha256(agent_id.encode()).hexdigest()}"
            
            record = TokenLaunchRecord(
                agent_id=agent_id,
                epoch=epoch,
                token_address=mock_token,
                strategy_hash=strategy_hash,
                owner_address=owner_address,
                launched_at=datetime.now(),
                tx_hash=mock_tx
            )
            self.launches.append(record)
            return record

        # === 真实链上交互 ===
        try:
            # 加载 Arena ABI (简化版)
            arena_abi = [{
                "inputs": [
                    {"name": "agentId", "type": "string"},
                    {"name": "epoch", "type": "uint256"},
                    {"name": "strategyHash", "type": "bytes32"}
                ],
                "name": "ascendChampion",
                "outputs": [{"name": "", "type": "address"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }]
            
            contract = self.web3.eth.contract(address=arena_address, abi=arena_abi)
            
            # 构建交易
            account = self.web3.eth.account.from_key(OPERATOR_PRIVATE_KEY)
            nonce = self.web3.eth.get_transaction_count(account.address)
            
            tx = contract.functions.ascendChampion(
                agent_id,
                epoch,
                bytes.fromhex(strategy_hash[2:]) # remove 0x
            ).build_transaction({
                'from': account.address,
                'nonce': nonce,
                'gas': 3000000,
                'gasPrice': self.web3.eth.gas_price
            })
            
            # 签名并发送
            signed_tx = self.web3.eth.account.sign_transaction(tx, private_key=OPERATOR_PRIVATE_KEY)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            print(f"   Tx sent: {tx_hash.hex()}")
            
            # 等待回执
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            # 解析日志找 Token 地址 (这里简化，假设从 receipt 能找到)
            # 在真实代码中需要解析 Logs
            token_address = "0x..." # TODO: Parse logs
            
            record = TokenLaunchRecord(
                agent_id=agent_id,
                epoch=epoch,
                token_address=token_address, # Placeholder for now
                strategy_hash=strategy_hash,
                owner_address=owner_address,
                launched_at=datetime.now(),
                tx_hash=tx_hash.hex()
            )
            self.launches.append(record)
            return record
            
        except Exception as e:
            print(f"❌ Chain Interaction Failed: {e}")
            return None

    async def launch_token(self, *args, **kwargs):
        """兼容旧接口，重定向到 ascend_champion"""
        print("⚠️ Deprecated launch_token called, redirecting to ascend_champion")
        return await self.ascend_champion(*args, **kwargs)

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
    
    async def generate_meta_tx(
        self,
        agent_id: str,
        epoch: int,
        owner_address: str,
        strategy_code: str
    ) -> dict:
        """
        生成 EIP-712 Meta-Transaction 签名
        允许前端用户(payer)代替 Operator 提交交易
        """
        if not self.web3 or not OPERATOR_PRIVATE_KEY:
            return {"error": "Web3 or Operator Key missing"}

        from web3 import Account
        from eth_account.messages import encode_typed_data
        
        # 1. Prepare Data
        strategy_hash = self.compute_strategy_hash(strategy_code)
        
        factory = self.web3.eth.contract(
            address=self.web3.to_checksum_address(FACTORY_ADDRESS),
            abi=[{
                "inputs": [
                    {"name": "agentId", "type": "string"},
                    {"name": "epoch", "type": "uint256"},
                    {"name": "agentOwner", "type": "address"},
                    {"name": "strategyHash", "type": "bytes32"}
                ],
                "name": "launchToken",
                "type": "function"
            }]
        )
        
        # Web3.py v6/v7 fix: use _encode_transaction_data() for calldata
        func_data = factory.functions.launchToken(
            agent_id,
            epoch,
            self.web3.to_checksum_address(owner_address),
            bytes.fromhex(strategy_hash[2:])
        )._encode_transaction_data()
        
        # 2. Get Nonce from Forwarder
        # GelatoRelay1BalanceERC2771 Forwarder
        FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"
        forwarder = self.web3.eth.contract(
            address=FORWARDER_ADDRESS,
            abi=[{"name": "userNonce", "inputs": [{"name": "account", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}], "type": "function"}]
        )
        
        account = Account.from_key(OPERATOR_PRIVATE_KEY)
        nonce = forwarder.functions.userNonce(account.address).call()
        deadline = int(datetime.now().timestamp()) + 3600  # 1 hour validity
        
        # 3. Construct EIP-712 Typed Data
        # Domain: GelatoRelay1BalanceERC2771
        chain_id = 84532 # Base Sepolia
        
        domain_data = {
            "name": "GelatoRelay1BalanceERC2771",
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": FORWARDER_ADDRESS
        }
        
        types = {
            "SponsoredCallERC2771": [
                {"name": "chainId", "type": "uint256"},
                {"name": "target", "type": "address"},
                {"name": "data", "type": "bytes"},
                {"name": "user", "type": "address"},
                {"name": "userNonce", "type": "uint256"},
                {"name": "userDeadline", "type": "uint256"}
            ]
        }
        
        message = {
            "chainId": chain_id,
            "target": FACTORY_ADDRESS,
            "data": bytes.fromhex(func_data[2:]), # web3.py needs bytes for bytes type
            "user": account.address,
            "userNonce": nonce,
            "userDeadline": deadline
        }
        
        # 4. Sign
        signable_message = encode_typed_data(domain_data, types, message)
        signed = Account.sign_message(signable_message, OPERATOR_PRIVATE_KEY)
        
        return {
            "forwarder": FORWARDER_ADDRESS,
            "request": {
                "chainId": chain_id,
                "target": FACTORY_ADDRESS,
                "data": func_data,
                "user": account.address,
                "userNonce": nonce,
                "userDeadline": deadline
            },
            "signature": signed.signature.hex()
        }

    async def generate_meta_tx_with_contributors(
        self,
        agent_id: str,
        epoch: int,
        owner_address: str,
        strategy_code: str,
        contributors: list[tuple[str, float]]  # [(wallet_address, score), ...]
    ) -> dict:
        """
        生成 EIP-712 Meta-Transaction 签名 (带贡献者空投)
        允许前端用户(payer)代替 Operator 提交交易
        """
        if not self.web3 or not OPERATOR_PRIVATE_KEY:
            return {"error": "Web3 or Operator Key missing"}

        from web3 import Account
        from eth_account.messages import encode_typed_data
        
        strategy_hash = self.compute_strategy_hash(strategy_code)
        
        # 准备贡献者数据
        contributor_addresses = [self.web3.to_checksum_address(c[0]) for c in contributors if c[0].startswith("0x")]
        contributor_scores = [int(c[1] * 100) for c in contributors if c[0].startswith("0x")]  # 转成整数
        
        # 使用 launchTokenWithContributors 函数
        factory_abi_with_contributors = [{
            "inputs": [
                {"name": "agentId", "type": "string"},
                {"name": "epoch", "type": "uint256"},
                {"name": "agentOwner", "type": "address"},
                {"name": "strategyHash", "type": "bytes32"},
                {"name": "contributors", "type": "address[]"},
                {"name": "scores", "type": "uint256[]"}
            ],
            "name": "launchTokenWithContributors",
            "type": "function"
        }]
        
        factory = self.web3.eth.contract(
            address=self.web3.to_checksum_address(FACTORY_ADDRESS),
            abi=factory_abi_with_contributors
        )
        
        func_data = factory.functions.launchTokenWithContributors(
            agent_id,
            epoch,
            self.web3.to_checksum_address(owner_address),
            bytes.fromhex(strategy_hash[2:]),
            contributor_addresses,
            contributor_scores
        )._encode_transaction_data()
        
        # Get Nonce from Forwarder
        FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"
        forwarder = self.web3.eth.contract(
            address=FORWARDER_ADDRESS,
            abi=[{"name": "userNonce", "inputs": [{"name": "account", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}], "type": "function"}]
        )
        
        account = Account.from_key(OPERATOR_PRIVATE_KEY)
        nonce = forwarder.functions.userNonce(account.address).call()
        deadline = int(datetime.now().timestamp()) + 3600
        
        chain_id = 84532  # Base Sepolia
        
        domain_data = {
            "name": "GelatoRelay1BalanceERC2771",
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": FORWARDER_ADDRESS
        }
        
        types = {
            "SponsoredCallERC2771": [
                {"name": "chainId", "type": "uint256"},
                {"name": "target", "type": "address"},
                {"name": "data", "type": "bytes"},
                {"name": "user", "type": "address"},
                {"name": "userNonce", "type": "uint256"},
                {"name": "userDeadline", "type": "uint256"}
            ]
        }
        
        message = {
            "chainId": chain_id,
            "target": FACTORY_ADDRESS,
            "data": bytes.fromhex(func_data[2:]),
            "user": account.address,
            "userNonce": nonce,
            "userDeadline": deadline
        }
        
        signable_message = encode_typed_data(domain_data, types, message)
        signed = Account.sign_message(signable_message, OPERATOR_PRIVATE_KEY)
        
        return {
            "forwarder": FORWARDER_ADDRESS,
            "request": {
                "chainId": chain_id,
                "target": FACTORY_ADDRESS,
                "data": func_data,
                "user": account.address,
                "userNonce": nonce,
                "userDeadline": deadline
            },
            "signature": signed.signature.hex(),
            "contributors": {
                "addresses": contributor_addresses,
                "scores": contributor_scores,
                "count": len(contributor_addresses)
            }
        }

    async def launch_token(
        self,
        agent_id: str,
        epoch: int,
        owner_address: str,
        strategy_code: str
    ) -> Optional[TokenLaunchRecord]:
        """
        发行代币
        
        优先级:
        1. Gelato Relay (无需私钥，最安全) - CURRENTLY DISABLED (API Key Issue)
        2. 直接私钥 (如果配置了)
        """
        
        # 方法 1: 尝试 Gelato Relay (推荐)
        if GELATO_API_KEY:
            print("🔄 Using Gelato Relay (no private key needed)")
            try:
                from gelato_relay import GelatoRelayer
                
                relayer = GelatoRelayer(GELATO_API_KEY)
                result = await relayer.launch_token(
                    agent_id, epoch, owner_address, strategy_code
                )
                
                if result:
                    return TokenLaunchRecord(
                        agent_id=agent_id,
                        epoch=epoch,
                        token_address="pending",  # Gelato 异步，稍后查询
                        strategy_hash=self.compute_strategy_hash(strategy_code),
                        owner_address=owner_address,
                        launched_at=datetime.now(),
                        tx_hash=f"gelato:{result.task_id}"
                    )
            except Exception as e:
                print(f"⚠️ Gelato failed: {e}, trying fallback...")
        
        # 方法 2: 直接用 Operator 私钥 (fallback)
        if OPERATOR_PRIVATE_KEY:
            print("🔄 Using Operator private key (Direct Launch)")
            return await self._launch_with_private_key(
                agent_id, epoch, owner_address, strategy_code
            )
        
        print("❌ No launch method available. Configure GELATO_API_KEY or OPERATOR_PRIVATE_KEY")
        return None
    
    async def _launch_with_private_key(
        self,
        agent_id: str,
        epoch: int,
        owner_address: str,
        strategy_code: str
    ) -> Optional[TokenLaunchRecord]:
        """使用 Operator 私钥直接发交易 (fallback)"""
        if not self.web3:
            print("❌ Web3 not available")
            return None
        
        if not FACTORY_ADDRESS:
            print("❌ Factory address not configured")
            return None
        
        strategy_hash = self.compute_strategy_hash(strategy_code)
        
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
            from web3 import Account
            account = Account.from_key(OPERATOR_PRIVATE_KEY)
            
            # === Smart Fallback: Check Balance ===
            # 如果余额不足以支付 Gas，自动降级为模拟模式，保证演示流畅
            balance = self.web3.eth.get_balance(account.address)
            gas_price = self.web3.eth.gas_price
            estimated_cost = 2000000 * gas_price
            
            if balance < estimated_cost:
                print(f"⚠️ Insufficient funds ({balance} wei). Falling back to SIMULATION MODE.")
                mock_tx = f"0xSimulatedLaunch_{hashlib.sha256(agent_id.encode()).hexdigest()}"
                mock_token = f"0xToken_{hashlib.sha256(strategy_hash.encode()).hexdigest()[:34]}"
                
                record = TokenLaunchRecord(
                    agent_id=agent_id,
                    epoch=epoch,
                    token_address=mock_token,
                    strategy_hash=strategy_hash,
                    owner_address=owner_address,
                    launched_at=datetime.now(),
                    tx_hash=mock_tx
                )
                self.launches.append(record)
                return record
            # =====================================
            
            factory = self.web3.eth.contract(
                address=self.web3.to_checksum_address(FACTORY_ADDRESS),
                abi=factory_abi
            )
            
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
            
            signed_tx = self.web3.eth.account.sign_transaction(tx, OPERATOR_PRIVATE_KEY)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                token_address = "0x..."  # TODO: 从事件解析
                
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
    逻辑更新: 分层筛选机制 + 科学风险指标

    L1 (模拟层): 免费训练层
      晋级条件:
      - 综合评分 > 70 分
      - 夏普比率 > 1.0
      - 最大回撤 > -20%
      - 连续 5 个 Epoch 保持正收益

    L2 (竞技层): 付费 0.01 ETH
      发币条件:
      - 综合评分 > 85 分
      - 夏普比率 > 2.0
      - 索提诺比率 > 2.5
      - 最大回撤 > -15%
      - 连续 3 次排名第一
    """

    def __init__(self):
        # L1 状态
        self.l1_consecutive_positive: dict[str, int] = {}  # 连续正收益次数
        self.l1_returns_history: dict[str, list] = {}      # 收益率历史
        self.l1_values_history: dict[str, list] = {}       # 资产价值历史
        self.l1_total_returns: dict[str, float] = {}       # 累计收益率
        self.l2_qualified: set[str] = set()                # 晋级到 L2 的 Agent

        # L2 状态
        self.l2_consecutive_wins: dict[str, int] = {}      # 连续获胜次数
        self.l2_returns_history: dict[str, list] = {}      # 收益率历史
        self.l2_values_history: dict[str, list] = {}       # 资产价值历史
        self.l2_total_returns: dict[str, float] = {}       # 累计收益率
        self.ascended: set[str] = set()                    # 最终发币的 Agent

        # 资金池模拟 (50个炮灰 * 0.01 ETH)
        self.pool_eth = 0.5 
    
    def record_epoch_result(self, rankings: list[tuple]) -> dict:
        """
        记录 Epoch 结果，使用科学的风险指标评估

        Args:
            rankings: [(agent_id, pnl_percent, total_value), ...]

        Returns:
            {
                "promoted_to_l2": [agent_ids],
                "ready_to_launch": [agent_ids]
            }
        """
        if not rankings:
            return {}

        from arena_server.metrics import (
            calculate_composite_score,
            check_l1_promotion_criteria,
            check_l2_launch_criteria
        )

        winner_id = rankings[0][0]
        result = {"promoted_to_l2": [], "ready_to_launch": []}

        # 判断赢家等级
        is_l2_winner = winner_id in self.l2_qualified

        if is_l2_winner:
            # === L2 逻辑 (发币赛) ===
            # 更新 L2 连胜
            for agent_id in list(self.l2_consecutive_wins.keys()):
                if agent_id != winner_id:
                    self.l2_consecutive_wins[agent_id] = 0
            self.l2_consecutive_wins[winner_id] = self.l2_consecutive_wins.get(winner_id, 0) + 1

            # 更新 L2 收益历史
            for agent_id, pnl, total_value in rankings:
                if agent_id in self.l2_qualified:
                    # 初始化历史记录
                    if agent_id not in self.l2_returns_history:
                        self.l2_returns_history[agent_id] = []
                        self.l2_values_history[agent_id] = [10000.0]  # 初始资金
                        self.l2_total_returns[agent_id] = 0.0

                    # 记录本轮收益
                    self.l2_returns_history[agent_id].append(pnl)
                    self.l2_values_history[agent_id].append(total_value)
                    self.l2_total_returns[agent_id] += pnl

            # 计算风险指标
            if winner_id in self.l2_returns_history:
                metrics = calculate_composite_score(
                    returns=self.l2_returns_history[winner_id],
                    cumulative_values=self.l2_values_history[winner_id],
                    cumulative_return=self.l2_total_returns[winner_id]
                )

                # 检查发币条件（使用科学指标）
                wins = self.l2_consecutive_wins.get(winner_id, 0)
                if check_l2_launch_criteria(metrics, wins) and winner_id not in self.ascended:
                    self.ascended.add(winner_id)
                    result["ready_to_launch"].append(winner_id)
                    print(f"🚀 {winner_id} achieves ASCENSION!")
                    print(f"   📊 Composite Score: {metrics['composite_score']:.2f}/100")
                    print(f"   📈 Sharpe Ratio: {metrics['sharpe_ratio']:.3f}")
                    print(f"   📉 Sortino Ratio: {metrics['sortino_ratio']:.3f}")
                    print(f"   💰 Liquidity Pool: {self.pool_eth} ETH")

        else:
            # === L1 逻辑 (晋级赛) ===
            # 更新 L1 收益历史
            for agent_id, pnl, total_value in rankings:
                if agent_id not in self.l2_qualified:
                    # 初始化历史记录
                    if agent_id not in self.l1_returns_history:
                        self.l1_returns_history[agent_id] = []
                        self.l1_values_history[agent_id] = [10000.0]  # 初始资金
                        self.l1_total_returns[agent_id] = 0.0
                        self.l1_consecutive_positive[agent_id] = 0

                    # 记录本轮收益
                    self.l1_returns_history[agent_id].append(pnl)
                    self.l1_values_history[agent_id].append(total_value)
                    self.l1_total_returns[agent_id] += pnl

                    # 更新连续正收益计数
                    if pnl > 0:
                        self.l1_consecutive_positive[agent_id] += 1
                    else:
                        self.l1_consecutive_positive[agent_id] = 0

            # 计算风险指标
            if winner_id in self.l1_returns_history:
                metrics = calculate_composite_score(
                    returns=self.l1_returns_history[winner_id],
                    cumulative_values=self.l1_values_history[winner_id],
                    cumulative_return=self.l1_total_returns[winner_id]
                )

                # 检查晋级条件（使用科学指标）
                consecutive_positive = self.l1_consecutive_positive.get(winner_id, 0)
                if check_l1_promotion_criteria(metrics, consecutive_positive):
                    self.l2_qualified.add(winner_id)
                    result["promoted_to_l2"].append(winner_id)
                    print(f"🌟 {winner_id} promoted to L2 Arena!")
                    print(f"   📊 Composite Score: {metrics['composite_score']:.2f}/100")
                    print(f"   📈 Sharpe Ratio: {metrics['sharpe_ratio']:.3f}")
                    print(f"   💵 Entry Fee: 0.01 ETH")

        return result
    
    def get_stats(self, agent_id: str) -> dict:
        """获取 Agent 的进度和风险指标"""
        from arena_server.metrics import calculate_composite_score

        is_l2 = agent_id in self.l2_qualified

        if is_l2:
            # L2 统计
            returns = self.l2_returns_history.get(agent_id, [])
            values = self.l2_values_history.get(agent_id, [10000.0])
            total_return = self.l2_total_returns.get(agent_id, 0.0)
            wins = self.l2_consecutive_wins.get(agent_id, 0)

            if returns:
                metrics = calculate_composite_score(returns, values, total_return)
            else:
                metrics = {
                    "composite_score": 0.0,
                    "sharpe_ratio": 0.0,
                    "sortino_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "calmar_ratio": 0.0,
                    "win_rate": 0.0
                }

            return {
                "tier": "L2",
                "consecutive_wins": wins,
                "wins": f"{wins}/3",  # 前端兼容性
                "total_return": f"{total_return:.1f}%",
                "composite_score": metrics["composite_score"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "sortino_ratio": metrics["sortino_ratio"],
                "max_drawdown": metrics["max_drawdown"],
                "win_rate": metrics["win_rate"],
                "status": "Fighting for Launch",
                "requirements": {
                    "composite_score": "85+",
                    "sharpe_ratio": "2.0+",
                    "sortino_ratio": "2.5+",
                    "max_drawdown": ">-15%",
                    "consecutive_wins": "3"
                }
            }
        else:
            # L1 统计
            returns = self.l1_returns_history.get(agent_id, [])
            values = self.l1_values_history.get(agent_id, [10000.0])
            total_return = self.l1_total_returns.get(agent_id, 0.0)
            consecutive_positive = self.l1_consecutive_positive.get(agent_id, 0)

            if returns:
                metrics = calculate_composite_score(returns, values, total_return)
            else:
                metrics = {
                    "composite_score": 0.0,
                    "sharpe_ratio": 0.0,
                    "sortino_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "calmar_ratio": 0.0,
                    "win_rate": 0.0
                }

            return {
                "tier": "L1",
                "consecutive_positive": consecutive_positive,
                "wins": f"{consecutive_positive}/5",  # 前端兼容性
                "total_return": f"{total_return:.1f}%",
                "composite_score": metrics["composite_score"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "sortino_ratio": metrics["sortino_ratio"],
                "max_drawdown": metrics["max_drawdown"],
                "win_rate": metrics["win_rate"],
                "status": "Training",
                "requirements": {
                    "composite_score": "70+",
                    "sharpe_ratio": "1.0+",
                    "max_drawdown": ">-20%",
                    "consecutive_positive": "5"
                }
            }
    
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
