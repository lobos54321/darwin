from web3 import Web3
from eth_account import Account
import os

# print(f"Web3 version: {Web3.version}") # Skipped

w3 = Web3()
acct = Account.create()
tx = {
    'to': acct.address,
    'value': 0,
    'gas': 21000,
    'gasPrice': 1000000000,
    'nonce': 0,
    'chainId': 1
}

signed = Account.sign_transaction(tx, acct.key)
print(f"Signed type: {type(signed)}")
print(f"Signed dir: {dir(signed)}")

try:
    print(f"rawTransaction: {signed.rawTransaction!r}")
except AttributeError:
    print("No rawTransaction attribute")

try:
    print(f"rawTransaction (snake): {signed.raw_transaction!r}")
except AttributeError:
    print("No raw_transaction attribute")
