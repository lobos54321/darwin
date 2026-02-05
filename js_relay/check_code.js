const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FORWARDER = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  
  console.log(`Checking code at ${FORWARDER}...`);
  const code = await provider.getCode(FORWARDER);
  
  if (code === "0x") {
    console.error("❌ No code at address! Wrong network or address?");
  } else {
    console.log(`✅ Code found (${code.length} bytes)`);
    
    // Check for getNonce selector: 0x2d0335ab
    const hasGetNonce = code.includes("2d0335ab"); // rudimentary check
    console.log(`   Likely has getNonce? ${hasGetNonce ? "YES" : "NO (selector not found in bytecode literal)"}`);
  }
}

main();
