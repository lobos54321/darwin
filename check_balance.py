from web3 import Web3
import os

rpc = "https://sepolia.base.org"
w3 = Web3(Web3.HTTPProvider(rpc))
address = "0xE9A11d3304b549c09403865E8220a05951C575A6"
balance_wei = w3.eth.get_balance(address)
balance_eth = w3.from_wei(balance_wei, 'ether')

print(f"Address: {address}")
print(f"Balance: {balance_eth} ETH")
