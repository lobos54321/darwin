const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const FACTORY_ADDRESS = process.env.DARWIN_FACTORY_ADDRESS;
const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";

const ABI = [
    "function arenaServer() view returns (address)",
    "function isTrustedForwarder(address forwarder) view returns (bool)",
    "function owner() view returns (address)"
];

async function main() {
    const provider = new ethers.JsonRpcProvider(RPC_URL);
    const factory = new ethers.Contract(FACTORY_ADDRESS, ABI, provider);

    console.log(`🔍 Inspecting DarwinFactory at ${FACTORY_ADDRESS}`);
    
    try {
        const arenaServer = await factory.arenaServer();
        const owner = await factory.owner();
        
        console.log(`   - arenaServer: ${arenaServer}`);
        console.log(`   - owner:       ${owner}`);
        
        // Check against the forwarder used in the script
        const SCRIPT_FORWARDER = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";
        const isTrusted = await factory.isTrustedForwarder(SCRIPT_FORWARDER);
        console.log(`   - isTrustedForwarder(${SCRIPT_FORWARDER}): ${isTrusted}`);

        // Also check if we (Operator) match arenaServer
        const OPERATOR_KEY = process.env.OPERATOR_PRIVATE_KEY;
        if (OPERATOR_KEY) {
            const wallet = new ethers.Wallet(OPERATOR_KEY);
            console.log(`   - Local Operator Address: ${wallet.address}`);
            console.log(`   - Match? ${wallet.address === arenaServer ? "✅ YES" : "❌ NO"}`);
        }

    } catch (e) {
        console.error("Error reading contract:", e);
    }
}

main();
