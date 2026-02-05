from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

chain_id = 84532
verifying_contract = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"
name = "GelatoRelay1BalanceERC2771"
version = "1"

domain_data = {
    "name": name,
    "version": version,
    "chainId": chain_id,
    "verifyingContract": verifying_contract
}

types = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"}
    ]
}

# Hashing logic simulation (using eth-account internals via hash_domain is hard, 
# so we construct a dummy message to get the domain hash indirectly or use a library if available)
# Actually, let's just use the fact that encode_typed_data computes it.

message = {
    "chainId": chain_id,
    "target": "0x0000000000000000000000000000000000000000",
    "data": b"",
    "user": "0x0000000000000000000000000000000000000000",
    "userNonce": 0,
    "userDeadline": 0
}

types["SponsoredCallERC2771"] = [
    {"name": "chainId", "type": "uint256"},
    {"name": "target", "type": "address"},
    {"name": "data", "type": "bytes"},
    {"name": "user", "type": "address"},
    {"name": "userNonce", "type": "uint256"},
    {"name": "userDeadline", "type": "uint256"}
]

structured_data = {
    "types": types,
    "domain": domain_data,
    "primaryType": "SponsoredCallERC2771",
    "message": message
}

# Access internal hashing to see domain separator
from eth_account._utils.structured_data.hashing import hash_domain
domain_separator = hash_domain(domain_data)
print(f"Calculated Domain Separator: {domain_separator.hex()}")
print(f"Expected Domain Separator:   fdb15942bfe11d2bacaf23218d54ecea78afb09e835c452e9ad71290cae06b03")
