import os
import sys
import json
import time
from web3 import Web3
from solcx import compile_standard, install_solc

# === 配置 ===
RPC_URL = os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
PRIVATE_KEY = os.getenv("OPERATOR_PRIVATE_KEY")
PLATFORM_WALLET = os.getenv("DARWIN_PLATFORM_WALLET", "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9")

# 如果没有配置私钥，提前报错
if not PRIVATE_KEY:
    print("❌ 错误: 请设置 OPERATOR_PRIVATE_KEY 环境变量")
    sys.exit(1)

# 连接 Base Sepolia
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    print("❌ 无法连接到 Base Sepolia RPC")
    sys.exit(1)

account = w3.eth.account.from_key(PRIVATE_KEY)
deployer_address = account.address
print(f"🔗 Connected to Base Sepolia")
print(f"👤 Deployer: {deployer_address}")
print(f"💰 Balance: {w3.from_wei(w3.eth.get_balance(deployer_address), 'ether')} ETH")

# === 1. 编译合约 ===
print("\n🔨 Compiling contracts...")
install_solc("0.8.20")

# 读取合约源码
contracts_dir = os.path.join(os.path.dirname(__file__), "..", "contracts")
contract_files = ["DarwinFactory.sol", "DarwinArena.sol", "DarwinToken.sol"]

sources = {}
for file in contract_files:
    with open(os.path.join(contracts_dir, file), "r") as f:
        sources[file] = {"content": f.read()}

# 编译 (包含 OpenZeppelin 映射)
# 注意: 这里假设 node_modules 在项目根目录
import_remappings = {
    "@openzeppelin/": os.path.join(os.path.dirname(__file__), "..", "node_modules", "@openzeppelin")
}

# 简化的编译配置
compiled_sol = compile_standard(
    {
        "language": "Solidity",
        "sources": sources,
        "settings": {
            "outputSelection": {
                "*": {
                    "*": ["abi", "metadata", "evm.bytecode", "evm.sourceMap"]
                }
            },
            "optimizer": {"enabled": True, "runs": 200},
            # "remappings": ["@openzeppelin/=node_modules/@openzeppelin/"] # 简单映射
        },
    },
    solc_version="0.8.20",
    allow_paths=[os.path.abspath(os.path.join(contracts_dir, ".."))]
)

print("✅ Compilation complete!")

def deploy_contract(contract_name, *args):
    print(f"\n🚀 Deploying {contract_name}...")
    
    # 提取 ABI 和 Bytecode
    bytecode = compiled_sol["contracts"][f"{contract_name}.sol"][contract_name]["evm"]["bytecode"]["object"]
    abi = compiled_sol["contracts"][f"{contract_name}.sol"][contract_name]["abi"]
    
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    
    # 构建交易
    construct_txn = contract.constructor(*args).build_transaction({
        "from": deployer_address,
        "nonce": w3.eth.get_transaction_count(deployer_address),
        "gasPrice": w3.eth.gas_price
    })
    
    # 签名并发送
    signed_txn = w3.eth.account.sign_transaction(construct_txn, private_key=PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
    print(f"   Waiting for tx: {tx_hash.hex()}...")
    
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    contract_address = tx_receipt.contractAddress
    print(f"✅ {contract_name} deployed at: {contract_address}")
    
    return contract_address, abi

# === 2. 部署流程 ===

try:
    # A. 部署 DarwinFactory
    # constructor(address arenaServer_, address platformWallet_, address trustedForwarder_)
    # 暂时把 trustedForwarder 设为 deployer，方便测试 Meta-Tx
    factory_address, factory_abi = deploy_contract("DarwinFactory", deployer_address, PLATFORM_WALLET, deployer_address)
    
    # B. 部署 DarwinArena
    # constructor(address _operator)
    arena_address, arena_abi = deploy_contract("DarwinArena", deployer_address)
    
    # === 3. 权限链接 (Linking) ===
    print("\n🔗 Linking contracts...")
    
    # C. Factory setArenaContract(Arena)
    print("   Setting Arena address in Factory...")
    factory = w3.eth.contract(address=factory_address, abi=factory_abi)
    tx = factory.functions.setArenaContract(arena_address).build_transaction({
        "from": deployer_address,
        "nonce": w3.eth.get_transaction_count(deployer_address),
        "gasPrice": w3.eth.gas_price
    })
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
    w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print("   -> Factory linked to Arena")
    time.sleep(2) # 等待 nonce 更新
    
    # D. Arena setFactory(Factory)
    print("   Setting Factory address in Arena...")
    arena = w3.eth.contract(address=arena_address, abi=arena_abi)
    tx = arena.functions.setFactory(factory_address).build_transaction({
        "from": deployer_address,
        "nonce": w3.eth.get_transaction_count(deployer_address),
        "gasPrice": w3.eth.gas_price
    })
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
    w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print("   -> Arena linked to Factory")
    
    print("\n✨ Deployment Summary ✨")
    print(f"DarwinFactory: {factory_address}")
    print(f"DarwinArena:   {arena_address}")
    print("\n👉 Please update your .env file with these addresses!")

except Exception as e:
    print(f"\n❌ Deployment failed: {e}")
