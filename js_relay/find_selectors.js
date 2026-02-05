const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const code = await provider.getCode(FORWARDER_ADDRESS);

  if (code === "0x") {
    console.log("No code found.");
    return;
  }

  console.log(`Scanning bytecode at ${FORWARDER_ADDRESS} (${code.length} bytes)...`);

  // Simple heuristic: Look for PUSH4 (0x63) followed by 4 bytes, then maybe EQ (0x14) or similar
  // Dispatcher usually looks like: DUP1, PUSH4 <sig>, EQ, PUSH2 <offset>, JUMPI
  
  const selectors = [];
  // Remove 0x
  const cleanCode = code.slice(2);
  
  for (let i = 0; i < cleanCode.length; i += 2) {
    const opcode = parseInt(cleanCode.substr(i, 2), 16);
    // 0x63 is PUSH4
    if (opcode === 0x63) {
      // Check if we have enough bytes left
      if (i + 10 <= cleanCode.length) {
          const selector = cleanCode.substr(i + 2, 8);
          // Check if followed by 0x14 (EQ) - strict check
          const nextOp = parseInt(cleanCode.substr(i + 10, 2), 16);
          if (nextOp === 0x14) {
             selectors.push("0x" + selector);
          } else {
             // Sometimes optimized code does GT/LT checks, but let's log potential PUSH4s anyway
             // selectors.push("0x" + selector + " (?)");
          }
      }
    }
  }

  console.log("Found Selectors:", selectors);
  
  // Known hashes to check
  const candidates = [
      "sponsoredCall((uint256,address,bytes,address,uint256,uint256),bytes)",
      "execute((uint256,address,bytes,address,uint256,uint256),bytes)",
      "relay((uint256,address,bytes,address,uint256,uint256),bytes)"
  ];

  for (const sig of candidates) {
      const hash = ethers.id(sig).slice(0, 10);
      console.log(`Checking ${sig}: ${hash} -> ${selectors.includes(hash) ? "✅ FOUND" : "❌"}`);
  }
}

main();
