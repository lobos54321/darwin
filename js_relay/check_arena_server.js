const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FACTORY_ADDRESS = process.env.DARWIN_FACTORY_ADDRESS;

const ABI = [
  "function arenaServer() view returns (address)",
  "function owner() view returns (address)"
];

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const contract = new ethers.Contract(FACTORY_ADDRESS, ABI, provider);
  
  console.log(`Checking config for Factory at ${FACTORY_ADDRESS}...`);

  try {
    const server = await contract.arenaServer();
    const owner = await contract.owner();
    
    console.log(`\n🏛️  Contract State:`);
    console.log(`   arenaServer: ${server}`);
    console.log(`   owner:       ${owner}`);
    
    const envOperator = process.env.OPERATOR_ADDRESS;
    console.log(`\n🔧 Local Config:`);
    console.log(`   OPERATOR_ADDRESS: ${envOperator}`);
    
    if (server.toLowerCase() === envOperator.toLowerCase()) {
      console.log(`\n✅ Match! The revert shouldn't happen if msg.sender is correct.`);
    } else {
      console.log(`\n❌ MISMATCH! Contract expects ${server}, but we signed as ${envOperator}.`);
    }

  } catch (e) {
    console.error("Error:", e);
  }
}

main();
