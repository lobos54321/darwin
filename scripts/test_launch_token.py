"""
测试发币脚本
需要设置环境变量 PRIVATE_KEY
"""

import os
import sys
from web3 import Web3

# 配置
RPC_URL = "https://sepolia.base.org"
FACTORY_ADDRESS = "0x63685E3Ff986Ae389496C08b6c18F30EBdb9fa71"

# Factory ABI (只需要 launchToken 函数)
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
        "inputs": [{"name": "agentId", "type": "string"}],
        "name": "agentToToken",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
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
    # 连接
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    print(f"Connected: {w3.is_connected()}")
    print(f"Chain ID: {w3.eth.chain_id}")
    
    # 合约
    factory = w3.eth.contract(address=FACTORY_ADDRESS, abi=FACTORY_ABI)
    
    # 检查 arenaServer
    arena_server = factory.functions.arenaServer().call()
    print(f"Arena Server: {arena_server}")
    
    # 获取私钥
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        print("\n❌ 请设置 PRIVATE_KEY 环境变量")
        print("export PRIVATE_KEY=0x...")
        print("\n或者用 Remix 手动测试:")
        print(f"1. 打开 https://remix.ethereum.org")
        print(f"2. At Address: {FACTORY_ADDRESS}")
        print(f"3. 调用 launchToken('TestWinner', 1, {arena_server}, 0x01...)")
        return
    
    # 获取账户
    account = w3.eth.account.from_key(private_key)
    print(f"Your address: {account.address}")
    
    # 检查余额
    balance = w3.eth.get_balance(account.address)
    print(f"Balance: {w3.from_wei(balance, 'ether')} ETH")
    
    if balance < w3.to_wei(0.001, 'ether'):
        print("❌ 余额不足，请先领取测试网 ETH")
        return
    
    # 发币参数
    agent_id = "TestWinner"
    epoch = 1
    agent_owner = account.address
    strategy_hash = b'\x01' + b'\x00' * 31  # bytes32
    
    print(f"\n🚀 Launching token for: {agent_id}")
    
    # 构建交易
    tx = factory.functions.launchToken(
        agent_id,
        epoch,
        agent_owner,
        strategy_hash
    ).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 3000000,
        'gasPrice': w3.eth.gas_price,
    })
    
    # 签名并发送
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"TX: {tx_hash.hex()}")
    
    # 等待确认
    print("Waiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"✅ Token launched!")
        
        # 查询代币地址
        token_address = factory.functions.agentToToken(agent_id).call()
        print(f"Token Address: {token_address}")
        print(f"View on Basescan: https://sepolia.basescan.org/address/{token_address}")
    else:
        print("❌ Transaction failed")


if __name__ == "__main__":
    main()
