const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const OPERATOR_ADDRESS = process.env.OPERATOR_ADDRESS;

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const balance = await provider.getBalance(OPERATOR_ADDRESS);
  console.log(`Address: ${OPERATOR_ADDRESS}`);
  console.log(`Balance: ${ethers.formatEther(balance)} ETH`);
}

main();
