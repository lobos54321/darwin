import os
import json
from web3 import Web3
from solcx import compile_files, install_solc
from dotenv import load_dotenv

# 加载环境变量
load_dotenv("/Users/boliu/darwin-workspace/project-darwin/.env")

# 配置
RPC_URL = "https://sepolia.base.org"
CHAIN_ID = 84532
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
OPERATOR_ADDRESS = os.getenv("OPERATOR_ADDRESS")
MY_ADDRESS = "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9"
GELATO_FORWARDER = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"

def deploy():
    print(f"🔌 Connecting to Base Sepolia...")
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        raise Exception("Connection failed")
    
    account = w3.eth.account.from_key(PRIVATE_KEY)
    print(f"👤 Deployer: {account.address}")
    
    # 编译合约
    print("🔨 Compiling contracts...")
    install_solc("0.8.20")
    
    # 切换到 contracts 目录，这样可以用相对路径，避免路径混乱
    contracts_dir = "/Users/boliu/darwin-workspace/project-darwin/contracts"
    original_cwd = os.getcwd()
    os.chdir(contracts_dir)
    
    try:
        # 编译
        compiled_sol = compile_files(
            ["DarwinFactory.sol"],
            output_values=["abi", "bin"],
            solc_version="0.8.20",
            base_path=".",
            import_remappings={
                "@openzeppelin": "node_modules/@openzeppelin"
            },
            allow_paths=[".", "node_modules"]
        )
    finally:
        os.chdir(original_cwd)
    
    # 查找编译结果
    contract_key = next((k for k in compiled_sol.keys() if ":DarwinFactory" in k), None)
    if not contract_key:
        raise Exception("Compilation failed: DarwinFactory not found")
        
    contract_interface = compiled_sol[contract_key]
    
    # 部署
    print("🚀 Deploying DarwinFactory...")
    DarwinFactory = w3.eth.contract(abi=contract_interface['abi'], bytecode=contract_interface['bin'])
    
    construct_txn = DarwinFactory.constructor(
        OPERATOR_ADDRESS,
        MY_ADDRESS,
        GELATO_FORWARDER
    ).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'chainId': CHAIN_ID,
    })
    
    print("Signing transaction...")
    signed_txn = w3.eth.account.sign_transaction(construct_txn, private_key=PRIVATE_KEY)
    
    # 兼容不同的 web3.py 版本
    raw_tx = getattr(signed_txn, 'rawTransaction', None)
    if raw_tx is None:
        raw_tx = getattr(signed_txn, 'rawTransaction', None) # 再次尝试（其实通常是同一个）
    if raw_tx is None:
        raw_tx = getattr(signed_txn, 'raw_transaction', None) # 尝试 snake_case
    if raw_tx is None:
        # 尝试字典访问
        try:
            raw_tx = signed_txn['rawTransaction']
        except:
            pass
            
    if raw_tx is None:
        print(f"Debug: signed_txn attributes: {dir(signed_txn)}")
        raise Exception("Cannot find rawTransaction in SignedTransaction object")

    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    print(f"⏳ Waiting for confirmation... Tx: {tx_hash.hex()}")
    
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    contract_address = tx_receipt.contractAddress
    print(f"✅ Deployed to: {contract_address}")
    
    # 更新 .env
    print("📝 Updating .env...")
    env_path = "/Users/boliu/darwin-workspace/project-darwin/.env"
    try:
        with open(env_path, "r") as f:
            lines = f.readlines()
        with open(env_path, "w") as f:
            updated = False
            for line in lines:
                if line.startswith("FACTORY_ADDRESS="):
                    f.write(f"FACTORY_ADDRESS={contract_address}\n")
                    updated = True
                elif line.startswith("DARWIN_FACTORY_ADDRESS="):
                    f.write(f"DARWIN_FACTORY_ADDRESS={contract_address}\n")
                    updated = True
                else:
                    f.write(line)
            if not updated:
                f.write(f"FACTORY_ADDRESS={contract_address}\n")
    except Exception as e:
        print(f"⚠️ Failed to update .env automatically: {e}")

if __name__ == "__main__":
    deploy()
