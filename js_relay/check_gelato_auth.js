const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";

const ABI = [
  "function gelato() view returns (address)"
];

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const contract = new ethers.Contract(FORWARDER_ADDRESS, ABI, provider);
  
  console.log(`Checking 'gelato' address on ${FORWARDER_ADDRESS}...`);
  
  try {
    const gelatoAddress = await contract.gelato();
    console.log(`✅ Authorized Gelato Address: ${gelatoAddress}`);
  } catch (e) {
    console.log(`❌ Failed to read gelato address: ${e.message}`);
  }
}

main();
