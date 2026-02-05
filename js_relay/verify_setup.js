const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FACTORY_ADDRESS = process.env.DARWIN_FACTORY_ADDRESS;
// The address we believe is the forwarder
const CANDIDATE_FORWARDER = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";
const OPERATOR_ADDRESS = process.env.OPERATOR_ADDRESS;

const FACTORY_ABI = [
  "function isTrustedForwarder(address forwarder) view returns (bool)"
];

const FORWARDER_ABI = [
  "function getNonce(address user) view returns (uint256)",
  "function nonces(address owner) view returns (uint256)"
];

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  
  console.log(`\n🔍 Verifying Setup on Chain ${await (await provider.getNetwork()).chainId}`);
  console.log(`   Factory: ${FACTORY_ADDRESS}`);
  console.log(`   Operator: ${OPERATOR_ADDRESS}`);
  console.log(`   Candidate Forwarder: ${CANDIDATE_FORWARDER}`);

  // 1. Check if Factory trusts this forwarder
  const factory = new ethers.Contract(FACTORY_ADDRESS, FACTORY_ABI, provider);
  try {
    const isTrusted = await factory.isTrustedForwarder(CANDIDATE_FORWARDER);
    console.log(`\n🏭 Factory Trust Check:`);
    console.log(`   Is ${CANDIDATE_FORWARDER} trusted? ${isTrusted ? "✅ YES" : "❌ NO"}`);
    
    if (!isTrusted) {
      console.error("   ⚠️ STOP: The factory does not trust this forwarder. We cannot use it.");
      return;
    }
  } catch (e) {
    console.error("   ❌ Error checking trust:", e.message);
  }

  // 2. Check Forwarder Nonce (Try both getNonce and nonces)
  const forwarder = new ethers.Contract(CANDIDATE_FORWARDER, FORWARDER_ABI, provider);
  
  console.log(`\n⏩ Forwarder Nonce Check:`);
  
  try {
    const n = await forwarder.getNonce(OPERATOR_ADDRESS);
    console.log(`   getNonce() success: ${n}`);
  } catch (e) {
    console.log(`   getNonce() failed (likely not this ABI)`);
  }

  try {
    const n = await forwarder.nonces(OPERATOR_ADDRESS);
    console.log(`   nonces() success: ${n}`);
  } catch (e) {
    console.log(`   nonces() failed (likely not this ABI)`);
  }
}

main();
