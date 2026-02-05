from web3 import Web3

w3 = Web3(Web3.HTTPProvider('https://sepolia.base.org'))

addresses = [
    "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c", # Address A (Currently used)
    "0xBf175FCC7086b4f9bd59d5EAE8eA67b8f940DE0d"  # Address B (Another common one)
]

abis = [
    '[{"inputs":[{"internalType":"address","name":"user","type":"address"}],"name":"getNonce","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]',
    '[{"inputs":[{"internalType":"address","name":"owner","type":"address"}],"name":"nonces","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]'
]

test_user = "0x70B221f73De34C314BD186C19de78E9929aefE7C"

print("🔍 Probing Forwarder Addresses...")

for addr in addresses:
    print(f"\nChecking {addr}...")
    if len(w3.eth.get_code(addr)) == 0:
        print("  ❌ No code")
        continue
        
    # Try getNonce
    try:
        c = w3.eth.contract(address=addr, abi=abis[0])
        nonce = c.functions.getNonce(test_user).call()
        print(f"  ✅ getNonce() success! Nonce: {nonce}")
    except Exception as e:
        print(f"  ❌ getNonce() failed: {e}")

    # Try nonces
    try:
        c = w3.eth.contract(address=addr, abi=abis[1])
        nonce = c.functions.nonces(test_user).call()
        print(f"  ✅ nonces() success! Nonce: {nonce}")
    except Exception as e:
        print(f"  ❌ nonces() failed: {e}")
