import os
from web3 import Web3
from eth_account import Account

def setup_wallet():
    # 生成新钱包
    acct = Account.create()
    private_key = acct.key.hex()
    address = acct.address
    
    print(f"\n🔑 Generated New Operator Wallet")
    print(f"Address:     {address}")
    print(f"Private Key: {private_key[:6]}...{private_key[-4:]} (Saved to .env)")
    
    # 更新 .env
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    
    new_lines = []
    key_updated = False
    addr_updated = False
    
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()
            
        for line in lines:
            if line.startswith("OPERATOR_PRIVATE_KEY="):
                new_lines.append(f"OPERATOR_PRIVATE_KEY={private_key}\n")
                key_updated = True
            elif line.startswith("OPERATOR_ADDRESS="):
                new_lines.append(f"OPERATOR_ADDRESS={address}\n")
                addr_updated = True
            else:
                new_lines.append(line)
    
    if not key_updated:
        new_lines.append(f"\nOPERATOR_PRIVATE_KEY={private_key}\n")
    if not addr_updated:
        new_lines.append(f"OPERATOR_ADDRESS={address}\n")
        
    with open(env_path, "w") as f:
        f.writelines(new_lines)
        
    print(f"✅ Updated {env_path}")
    print(f"\n👉 ACTION REQUIRED: Send 0.02 Sepolia ETH to {address}")

if __name__ == "__main__":
    setup_wallet()
