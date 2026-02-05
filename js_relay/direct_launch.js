const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

// Configuration
const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FACTORY_ADDRESS = process.env.DARWIN_FACTORY_ADDRESS;
const OPERATOR_PRIVATE_KEY = process.env.OPERATOR_PRIVATE_KEY;

if (!OPERATOR_PRIVATE_KEY || !FACTORY_ADDRESS) {
    console.error("❌ Missing env vars");
    process.exit(1);
}

const FACTORY_ABI = [
    "function launchToken(string agentId, uint256 epoch, address agentOwner, bytes32 strategyHash) external returns (address)"
];

async function main() {
    const provider = new ethers.JsonRpcProvider(RPC_URL);
    const wallet = new ethers.Wallet(OPERATOR_PRIVATE_KEY, provider);

    console.log(`🚀 Direct Launch Mode`);
    console.log(`   Operator: ${wallet.address}`);
    console.log(`   Factory:  ${FACTORY_ADDRESS}`);

    // Check balance first
    const balance = await provider.getBalance(wallet.address);
    console.log(`   Balance:  ${ethers.formatEther(balance)} ETH`);

    if (balance < ethers.parseEther("0.001")) {
        console.error("\n❌ Insufficient funds! Please send ~0.005 ETH to the Operator address.");
        process.exit(1);
    }

    // Parse args
    const args = process.argv.slice(2);
    if (args.length < 4) {
        console.error("Usage: node direct_launch.js <agentId> <epoch> <owner> <strategyCode>");
        process.exit(1);
    }
    const [agentId, epoch, ownerAddress, strategyCode] = args;

    const iface = new ethers.Interface(FACTORY_ABI);
    const strategyHash = ethers.keccak256(ethers.toUtf8Bytes(strategyCode));

    console.log(`\n📤 Submitting transaction...`);
    
    try {
        const contract = new ethers.Contract(FACTORY_ADDRESS, FACTORY_ABI, wallet);
        const tx = await contract.launchToken(
            agentId,
            parseInt(epoch),
            ownerAddress,
            strategyHash
        );
        
        console.log(`   Tx Hash: ${tx.hash}`);
        console.log("   Waiting for confirmation...");
        
        const receipt = await tx.wait();
        console.log(`\n✅ Token Launched!`);
        console.log(`   Block: ${receipt.blockNumber}`);
        
        // Output result for parent process
        console.log(`\n__RESULT__${JSON.stringify({ txHash: tx.hash, status: "success" })}__END__`);

    } catch (error) {
        console.error(`\n❌ Transaction Failed:`, error.message);
        process.exit(1);
    }
}

main();
