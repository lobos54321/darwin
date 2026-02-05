from web3 import Web3

w3 = Web3()
# Create dummy contract
abi = [{"inputs": [], "name": "testFunc", "outputs": [], "stateMutability": "nonpayable", "type": "function"}]
contract = w3.eth.contract(address="0x0000000000000000000000000000000000000000", abi=abi)

func = contract.functions.testFunc()
print("Dir of function object:")
print([x for x in dir(func) if "encode" in x.lower() or "build" in x.lower()])
