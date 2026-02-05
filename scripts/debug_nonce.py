from web3 import Web3
from eth_abi import decode

w3 = Web3(Web3.HTTPProvider('https://sepolia.base.org'))
addr = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"
user = "0x70B221f73De34C314BD186C19de78E9929aefE7C"

print(f"🔍 Probing userNonce for {user} at {addr}...")

# 1. Try standard userNonce(address) -> 0x279b90c7
# keccak('userNonce(address)').slice(0,4)
selector = "0x279b90c7"
# Pad address to 32 bytes
padded_user = "000000000000000000000000" + user[2:]
data = selector + padded_user

print(f"  Call Data: {data}")

try:
    result = w3.eth.call({"to": addr, "data": data})
    print(f"✅ Raw result: {result.hex()}")
    nonce = int(result.hex(), 16)
    print(f"✅ Decoded Nonce: {nonce}")
except Exception as e:
    print(f"❌ userNonce(address) failed: {e}")

# 2. Try getNonce(address) -> 0x2d0335ab (Legacy?)
selector_get = "0x2d0335ab"
data_get = selector_get + padded_user
try:
    result = w3.eth.call({"to": addr, "data": data_get})
    print(f"✅ getNonce(address) result: {int(result.hex(), 16)}")
except Exception as e:
    print(f"❌ getNonce(address) failed: {e}")
