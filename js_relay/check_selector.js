const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";

async function main() {
    const provider = new ethers.JsonRpcProvider(RPC_URL);
    
    // Attempt 1: sponsoredCall
    // struct SponsoredCallERC2771 { uint256 chainId; address target; bytes data; address user; uint256 userNonce; uint256 userDeadline; }
    const sig1 = "sponsoredCall((uint256,address,bytes,address,uint256,uint256),bytes)";
    const sel1 = ethers.id(sig1).slice(0, 10);

    // Attempt 2: execute (standard GelatoRelay?)
    // This signature was used in older docs but might verify differently
    // Actually, GelatoRelay1BalanceERC2771 might inherit GelatoRelayERC2771
    
    console.log(`Checking selectors on ${FORWARDER_ADDRESS}...`);
    console.log(`1. ${sig1} -> ${sel1}`);

    const code = await provider.getCode(FORWARDER_ADDRESS);
    
    if (code.includes(sel1.slice(2))) {
        console.log(`✅ MATCH! Function 'sponsoredCall' found.`);
    } else {
        console.log(`❌ 'sponsoredCall' NOT found.`);
    }
}

main();
