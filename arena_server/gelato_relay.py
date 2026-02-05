"""
Gelato Relay 集成 (REST API 版本)
使用 Operator Key 签名，通过 Gelato V2 REST API 发送
"""

import os
import json
import hashlib
import time
import requests
from typing import Optional
from dataclasses import dataclass
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

# Gelato V2 REST API
GELATO_RELAY_URL = "https://relay.gelato.digital/relays/v2/sponsored-call-erc2771"

# 配置
GELATO_API_KEY = os.getenv("GELATO_API_KEY", "")
OPERATOR_PRIVATE_KEY = os.getenv("OPERATOR_PRIVATE_KEY", "")
BASE_SEPOLIA_CHAIN_ID = 84532
FACTORY_ADDRESS = os.getenv("FACTORY_ADDRESS") or os.getenv("DARWIN_FACTORY_ADDRESS", "0x8a80f4668dDF36D76a973fd8940A6FA500230621")

# Gelato Forwarder / Relay Contract (Base Sepolia)
GELATO_FORWARDER = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"

# Forwarder ABI
FORWARDER_ABI = [
    {
        "inputs": [{"name": "_user", "type": "address"}],
        "name": "userNonce",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Factory ABI
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
    task_id: str
    status: str
    tx_hash: Optional[str] = None


class GelatoRelayer:
    def __init__(self):
        if not GELATO_API_KEY:
            print("⚠️ GELATO_API_KEY missing")
        if not OPERATOR_PRIVATE_KEY:
            print("⚠️ OPERATOR_PRIVATE_KEY missing")
            
        self.w3 = Web3(Web3.HTTPProvider("https://sepolia.base.org"))
        
        if OPERATOR_PRIVATE_KEY:
            self.operator = Account.from_key(OPERATOR_PRIVATE_KEY)
            print(f"🤖 Gelato Operator: {self.operator.address}")
        else:
            self.operator = None

    def _get_user_nonce(self, user_address: str) -> int:
        """从 Gelato 合约获取 userNonce"""
        try:
            contract = self.w3.eth.contract(address=GELATO_FORWARDER, abi=FORWARDER_ABI)
            return contract.functions.userNonce(user_address).call()
        except Exception as e:
            print(f"⚠️ Failed to get nonce, using 0. Error: {e}")
            return 0

    def _sign_sponsored_call_erc2771(
        self,
        target: str,
        data: str,
        chain_id: int,
        nonce: int,
        deadline: int
    ) -> str:
        """
        构建并签名 SponsoredCallERC2771
        结构参考: GelatoRelay1BalanceERC2771Base.sol
        """
        
        # EIP-712 Domain
        domain_data = {
            "name": "GelatoRelay1BalanceERC2771", # 注意：名字可能因部署而异，通常是合约名
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": GELATO_FORWARDER
        }
        
        # EIP-712 Types
        # SponsoredCallERC2771(uint256 chainId,address target,bytes data,address user,uint256 userNonce,uint256 userDeadline)
        types = {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"}
            ],
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
            "target": target,
            "data": bytes.fromhex(data[2:]) if isinstance(data, str) and data.startswith("0x") else data,
            "user": self.operator.address,
            "userNonce": nonce,
            "userDeadline": deadline
        }
        
        structured_data = {
            "types": types,
            "domain": domain_data,
            "primaryType": "SponsoredCallERC2771",
            "message": message
        }
        
        signable_msg = encode_typed_data(full_message=structured_data)
        signed_msg = self.operator.sign_message(signable_msg)
        return signed_msg.signature.hex()

    async def launch_token(
        self,
        agent_id: str,
        epoch: int,
        owner_address: str,
        strategy_code: str
    ) -> Optional[GelatoTaskResult]:
        
        if not self.operator:
            print("❌ Operator key missing")
            return None
            
        print(f"🔄 Preparing Gelato REST API Request...")
        print(f"   Target: {FACTORY_ADDRESS}")
        
        # 1. 编码合约调用
        contract = self.w3.eth.contract(abi=FACTORY_ABI)
        strategy_hash = "0x" + hashlib.sha256(strategy_code.encode()).hexdigest()
        
        call_data = contract.encode_abi(
            "launchToken",
            args=[agent_id, epoch, owner_address, bytes.fromhex(strategy_hash[2:])]
        )
        
        # 2. 获取 Nonce
        nonce = self._get_user_nonce(self.operator.address)
        print(f"   Nonce: {nonce}")
        
        # 3. 签名
        deadline = int(time.time()) + 3600 # 1 hour
        signature = self._sign_sponsored_call_erc2771(
            target=FACTORY_ADDRESS,
            data=call_data,
            chain_id=BASE_SEPOLIA_CHAIN_ID,
            nonce=nonce,
            deadline=deadline
        )
        
        # 4. 发送 REST API 请求
        try:
            payload = {
                "chainId": BASE_SEPOLIA_CHAIN_ID,
                "target": FACTORY_ADDRESS,
                "data": call_data,
                "user": self.operator.address,
                "userNonce": nonce,
                "userDeadline": deadline,
                "userSignature": signature,
                "sponsorApiKey": GELATO_API_KEY
            }
            
            print("   Sending to Gelato REST API...")
            resp = requests.post(GELATO_RELAY_URL, json=payload, timeout=30)
            
            if resp.status_code == 200:
                result = resp.json()
                task_id = result.get("taskId")
                if task_id:
                    print(f"✅ Gelato Task ID: {task_id}")
                    return GelatoTaskResult(task_id=task_id, status="pending")
            
            # Error handling
            print(f"❌ Gelato Error ({resp.status_code}): {resp.text}")
            return None
                
        except Exception as e:
            print(f"❌ Exception: {e}")
            return None

    async def check_task_status(self, task_id: str) -> Optional[GelatoTaskResult]:
        try:
            resp = requests.get(f"https://relay.gelato.digital/tasks/status/{task_id}")
            data = resp.json()
            task = data.get("task", {})
            status = task.get("taskState", "Pending")
            tx_hash = task.get("transactionHash")
            
            return GelatoTaskResult(
                task_id=task_id,
                status=status,
                tx_hash=tx_hash
            )
        except:
            return None
