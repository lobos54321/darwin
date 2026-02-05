from web3 import Web3
from eth_account import Account
import os
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("OPERATOR_PRIVATE_KEY")
if not key:
    print("No Private Key found!")
else:
    account = Account.from_key(key)
    print(f"Operator Address: {account.address}")
