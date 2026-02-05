from web3 import Web3
from eth_abi import encode

def keccak_text(text):
    return Web3.keccak(text=text)

def keccak_bytes(data):
    return Web3.keccak(primitive=data)

# Params
name = "GelatoRelay1BalanceERC2771"
version = "1"
chain_id = 84532
verifying_contract = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"

# 1. EIP712_DOMAIN_TYPEHASH
domain_type_string = "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
domain_type_hash = keccak_text(domain_type_string)

# 2. Encode Data
encoded = encode(
    ['bytes32', 'bytes32', 'bytes32', 'uint256', 'address'],
    [
        domain_type_hash,
        keccak_text(name),
        keccak_text(version),
        chain_id,
        verifying_contract
    ]
)

# 3. Calculate Separator
separator = keccak_bytes(encoded)

print(f"Calculated: {separator.hex()}")
print(f"Contract:   0xfdb15942bfe11d2bacaf23218d54ecea78afb09e835c452e9ad71290cae06b03")

if separator.hex() == "0xfdb15942bfe11d2bacaf23218d54ecea78afb09e835c452e9ad71290cae06b03":
    print("✅ Domain Separator MATCHES!")
else:
    print("❌ Domain Separator MISMATCH!")
