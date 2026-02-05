from web3 import Web3
from eth_abi import decode

w3 = Web3(Web3.HTTPProvider('https://sepolia.base.org'))
addr = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"

print(f"🔍 Probing EIP-712 Domain for {addr}...")

# 1. Try eip712Domain() (EIP-5267 standard)
# returns (bytes1 fields, string name, string version, uint256 chainId, address verifyingContract, bytes32 salt, uint256[] extensions)
try:
    # Function signature: eip712Domain()
    selector = w3.keccak(text="eip712Domain()")[:4]
    result = w3.eth.call({"to": addr, "data": selector.hex()})
    
    # Decode: bytes1, string, string, uint256, address, bytes32, uint256[]
    # Note: decoding might vary if not fully compliant, but let's try standard
    decoded = decode(
        ['bytes1', 'string', 'string', 'uint256', 'address', 'bytes32', 'uint256[]'],
        result
    )
    print("\n✅ Found eip712Domain():")
    print(f"  Fields: {decoded[0].hex()}")
    print(f"  Name: {decoded[1]}")
    print(f"  Version: {decoded[2]}")
    print(f"  ChainId: {decoded[3]}")
    print(f"  VerifyingContract: {decoded[4]}")
    print(f"  Salt: {decoded[5].hex()}")
except Exception as e:
    print(f"\n❌ eip712Domain() failed: {e}")

# 2. Try simple getters if standard fails
# name()
try:
    c = w3.eth.contract(address=addr, abi=[{"name":"name","inputs":[],"outputs":[{"type":"string"}],"type":"function"}])
    print(f"\nName: {c.functions.name().call()}")
except:
    pass

# version()
try:
    c = w3.eth.contract(address=addr, abi=[{"name":"version","inputs":[],"outputs":[{"type":"string"}],"type":"function"}])
    print(f"Version: {c.functions.version().call()}")
except:
    pass

# DOMAIN_SEPARATOR()
try:
    c = w3.eth.contract(address=addr, abi=[{"name":"DOMAIN_SEPARATOR","inputs":[],"outputs":[{"type":"bytes32"}],"type":"function"}])
    ds = c.functions.DOMAIN_SEPARATOR().call()
    print(f"\nDOMAIN_SEPARATOR: {ds.hex()}")
except:
    pass
