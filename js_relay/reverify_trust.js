const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FACTORY_ADDRESS = process.env.DARWIN_FACTORY_ADDRESS;
const FORWARDER = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";

const ABI = [
  "function isTrustedForwarder(address forwarder) view returns (bool)"
];

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const contract = new ethers.Contract(FACTORY_ADDRESS, ABI, provider);
  
  console.log(`Checking trust for ${FORWARDER} on ${FACTORY_ADDRESS}...`);
  
  try {
    const isTrusted = await contract.isTrustedForwarder(FORWARDER);
    console.log(`Is Trusted? ${isTrusted}`);
  } catch (e) {
    console.error("Error:", e);
  }
}

main();
