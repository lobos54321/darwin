#!/usr/bin/env python3
"""
测试脚本：直接发送交易到 DarwinFactory（绕过 Gelato）
需要有 ETH 的钱包私钥

用法：
export PRIVATE_KEY=0x你的私钥
python3 scripts/test_direct_launch.py
"""

import os
import sys
import hashlib
from web3 import Web3

# 配置
RPC_URL = "https://sepolia.base.org"
FACTORY_ADDRESS = os.getenv("FACTORY_ADDRESS", "0x8a80f4668dDF36D76a973fd8940A6FA500230621")
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")

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
    },
    {
        "inputs": [],
        "name": "arenaServer",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

def main():
    if not PRIVATE_KEY:
        print("❌ 请设置 PRIVATE_KEY 环境变量")
        print("   export PRIVATE_KEY=0x你的私钥")
        sys.exit(1)
    
    print("=" * 60)
    print("🧬 Darwin Factory 直接发币测试")
    print("=" * 60)
    
    # 连接
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print("❌ 无法连接到 Base Sepolia")
        sys.exit(1)
    
    # 钱包
    account = w3.eth.account.from_key(PRIVATE_KEY)
    balance = w3.eth.get_balance(account.address)
    print(f"📍 钱包地址: {account.address}")
    print(f"💰 余额: {w3.from_wei(balance, 'ether'):.6f} ETH")
    
    if balance < w3.to_wei(0.001, 'ether'):
        print("❌ 余额不足，需要至少 0.001 ETH")
        sys.exit(1)
    
    # 合约
    factory = w3.eth.contract(address=FACTORY_ADDRESS, abi=FACTORY_ABI)
    
    # 检查 arenaServer
    try:
        arena_server = factory.functions.arenaServer().call()
        print(f"🏟️ Arena Server: {arena_server}")
        
        if arena_server.lower() != account.address.lower():
            print(f"⚠️ 警告: 你的地址不是 arenaServer!")
            print(f"   合约期望: {arena_server}")
            print(f"   你的地址: {account.address}")
            print("   交易可能会 revert")
    except Exception as e:
        print(f"⚠️ 无法读取 arenaServer: {e}")
    
    # 测试参数
    agent_id = "TestChampion_001"
    epoch = 1
    owner = account.address  # 自己作为 owner
    strategy_code = "def strategy(): return 'buy'"
    strategy_hash = "0x" + hashlib.sha256(strategy_code.encode()).hexdigest()
    
    print(f"\n📋 发币参数:")
    print(f"   Agent ID: {agent_id}")
    print(f"   Epoch: {epoch}")
    print(f"   Owner: {owner}")
    print(f"   Strategy Hash: {strategy_hash[:18]}...")
    
    # 构建交易
    try:
        tx = factory.functions.launchToken(
            agent_id,
            epoch,
            owner,
            bytes.fromhex(strategy_hash[2:])
        ).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 500000,
            'gasPrice': w3.eth.gas_price,
            'chainId': 84532
        })
        
        print(f"\n🔄 发送交易...")
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"📝 Tx Hash: {tx_hash.hex()}")
        
        print("⏳ 等待确认...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        
        if receipt.status == 1:
            print(f"✅ 交易成功!")
            print(f"   Gas Used: {receipt.gasUsed}")
            print(f"   Block: {receipt.blockNumber}")
            # TODO: 解析 logs 获取新 token 地址
        else:
            print(f"❌ 交易失败 (reverted)")
            
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
