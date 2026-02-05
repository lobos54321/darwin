const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";

const ABI = [
  "function eip712Domain() view returns (bytes1 fields, string name, string version, uint256 chainId, address verifyingContract, bytes32 salt, uint256[] extensions)",
  "function DOMAIN_SEPARATOR() view returns (bytes32)"
];

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const contract = new ethers.Contract(FORWARDER_ADDRESS, ABI, provider);
  
  console.log(`Checking domain for ${FORWARDER_ADDRESS}...`);

  try {
    const domain = await contract.eip712Domain();
    console.log("✅ eip712Domain() found:");
    console.log("   Name:", domain.name);
    console.log("   Version:", domain.version);
    console.log("   ChainId:", domain.chainId.toString());
    console.log("   VerifyingContract:", domain.verifyingContract);
  } catch (e) {
    console.log("❌ eip712Domain() failed or not present.");
  }

  try {
    const sep = await contract.DOMAIN_SEPARATOR();
    console.log("✅ DOMAIN_SEPARATOR() found:", sep);
  } catch (e) {
    console.log("❌ DOMAIN_SEPARATOR() failed.");
  }
}

main();
