const { ethers } = require("ethers");
const { GelatoRelay } = require("@gelatonetwork/relay-sdk");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";
const OPERATOR_ADDRESS = process.env.OPERATOR_ADDRESS;

// Alternate ABIs to test
const ABI = [
  "function getNonce(address user) view returns (uint256)",
  "function userNonce(address user) view returns (uint256)",
  "function nonce(address user) view returns (uint256)"
];

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const contract = new ethers.Contract(FORWARDER_ADDRESS, ABI, provider);
  
  console.log(`Checking alternate nonce methods for ${OPERATOR_ADDRESS}...`);

  try {
    const n = await contract.userNonce(OPERATOR_ADDRESS);
    console.log(`✅ userNonce() success: ${n}`);
  } catch (e) {
    console.log(`❌ userNonce() failed`);
  }

  try {
    const n = await contract.nonce(OPERATOR_ADDRESS);
    console.log(`✅ nonce() success: ${n}`);
  } catch (e) {
    console.log(`❌ nonce() failed`);
  }

  // SDK Check
  try {
    console.log("\nChecking SDK methods...");
    const relay = new GelatoRelay();
    // Inspect prototype
    console.log("SDK Relay keys:", Object.getOwnPropertyNames(Object.getPrototypeOf(relay)));
  } catch (e) {
    console.error("SDK inspect failed:", e);
  }
}

main();
