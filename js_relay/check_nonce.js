const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"; // GelatoRelayERC2771
const OPERATOR_ADDRESS = process.env.OPERATOR_ADDRESS;

const ABI = [
  "function getNonce(address user) view returns (uint256)"
];

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const contract = new ethers.Contract(FORWARDER_ADDRESS, ABI, provider);
  
  try {
    console.log(`Checking nonce for ${OPERATOR_ADDRESS} on ${FORWARDER_ADDRESS}...`);
    const nonce = await contract.getNonce(OPERATOR_ADDRESS);
    console.log(`Nonce: ${nonce.toString()}`);
  } catch (e) {
    console.error("Error fetching nonce:", e);
  }
}

main();
