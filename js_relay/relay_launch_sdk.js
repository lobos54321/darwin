const { GelatoRelay } = require("@gelatonetwork/relay-sdk");
const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

// Config
const GELATO_API_KEY = process.env.GELATO_API_KEY;
const FACTORY_ADDRESS = process.env.DARWIN_FACTORY_ADDRESS;
const OPERATOR_PRIVATE_KEY = process.env.OPERATOR_PRIVATE_KEY;
const CHAIN_ID = 84532n;

if (!GELATO_API_KEY || !FACTORY_ADDRESS || !OPERATOR_PRIVATE_KEY) {
    console.error("❌ Missing configuration in .env");
    process.exit(1);
}

const FACTORY_ABI = [
    "function launchToken(string agentId, uint256 epoch, address agentOwner, bytes32 strategyHash) external returns (address)"
];

async function main() {
    const provider = new ethers.JsonRpcProvider(process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org");
    const wallet = new ethers.Wallet(OPERATOR_PRIVATE_KEY, provider);
    
    // Configure SDK to use the new Gelato Cloud endpoint
    const relay = new GelatoRelay({
        url: "https://api.gelato.cloud"
    });

    console.log("🚀 Launching via Gelato SDK...");
    console.log(`   User: ${wallet.address}`);
    console.log(`   Target: ${FACTORY_ADDRESS}`);

    // Parse args
    const args = process.argv.slice(2);
    if (args.length < 4) {
        console.error("Usage: node relay_launch_sdk.js <agentId> <epoch> <owner> <strategyCode>");
        process.exit(1);
    }
    const [agentId, epoch, ownerAddress, strategyCode] = args;

    // Encode payload
    const iface = new ethers.Interface(FACTORY_ABI);
    const strategyHash = ethers.keccak256(ethers.toUtf8Bytes(strategyCode));
    const data = iface.encodeFunctionData("launchToken", [
        agentId,
        parseInt(epoch),
        ownerAddress,
        strategyHash
    ]);

    // Build Request
    const request = {
        chainId: CHAIN_ID,
        target: FACTORY_ADDRESS,
        data: data,
        user: wallet.address
    };

    console.log("   Sending sponsoredCallERC2771...");

    try {
        // SDK handles nonce, signature, and endpoint automatically
        // Must pass 'wallet' (Signer) not 'provider' to sign locally
        const relayResponse = await relay.sponsoredCallERC2771(
            request,
            wallet, 
            GELATO_API_KEY
        );

        console.log(`\n✅ Task Submitted!`);
        console.log(`   Task ID: ${relayResponse.taskId}`);
        console.log(`\n__RESULT__${JSON.stringify({ taskId: relayResponse.taskId, status: "pending" })}__END__`);

    } catch (error) {
        console.error("❌ SDK Error:", error.message);
        if (error.response) {
            console.error("   Response:", error.response.data);
        }
        process.exit(1);
    }
}

main();
