const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const RPC_URL = process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org";
const FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";

async function main() {
    const provider = new ethers.JsonRpcProvider(RPC_URL);
    
    // ABI for GelatoRelayERC2771.execute
    // struct SponsoredCallERC2771 {
    //     uint256 chainId;
    //     address target;
    //     bytes data;
    //     address user;
    //     uint256 userNonce;
    //     uint256 userDeadline;
    // }
    // function execute(SponsoredCallERC2771 calldata _call, bytes calldata _userSignature) external;

    const ABI = [
        "function execute((uint256 chainId, address target, bytes data, address user, uint256 userNonce, uint256 userDeadline) req, bytes signature) external"
    ];

    const iface = new ethers.Interface(ABI);
    const selector = iface.getFunction("execute").selector;
    
    console.log(`Checking 'execute' selector: ${selector} on ${FORWARDER_ADDRESS}...`);
    
    const code = await provider.getCode(FORWARDER_ADDRESS);
    if (code.includes(selector.slice(2))) {
        console.log("✅ Selector found in contract bytecode!");
    } else {
        console.log("❌ Selector NOT found. ABI might be different.");
        // Try to dump plausible selectors? No, let's stick to verifying this one.
    }
}

main();
