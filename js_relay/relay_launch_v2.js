const { ethers } = require("ethers");
const axios = require("axios");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

// Configuration
// PROVEN Endpoint for Gelato Relay
const GELATO_RELAY_URL = "https://relay.gelato.digital/relays/v2/sponsored-call-erc2771";
const CHAIN_ID = 84532n; // Base Sepolia
const FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"; // GelatoRelayERC2771
const FACTORY_ADDRESS = process.env.DARWIN_FACTORY_ADDRESS;
const OPERATOR_PRIVATE_KEY = process.env.OPERATOR_PRIVATE_KEY;
const GELATO_API_KEY = process.env.GELATO_API_KEY;

if (!OPERATOR_PRIVATE_KEY || !GELATO_API_KEY || !FACTORY_ADDRESS) {
    console.error("❌ Missing env vars (OPERATOR_PRIVATE_KEY, GELATO_API_KEY, DARWIN_FACTORY_ADDRESS)");
    process.exit(1);
}

// ABIs
const FORWARDER_ABI = [
    "function userNonce(address user) view returns (uint256)"
];

const FACTORY_ABI = [
    "function launchToken(string agentId, uint256 epoch, address agentOwner, bytes32 strategyHash) external returns (address)"
];

async function main() {
    // 1. Setup Provider & Signer
    const provider = new ethers.JsonRpcProvider(process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org");
    const wallet = new ethers.Wallet(OPERATOR_PRIVATE_KEY, provider);
    const user = wallet.address;

    console.log(`🚀 Preparing Relay Launch (REST API)`);
    console.log(`   User (Operator): ${user}`);
    console.log(`   Factory: ${FACTORY_ADDRESS}`);
    console.log(`   Forwarder: ${FORWARDER_ADDRESS}`);
    console.log(`   Endpoint: ${GELATO_RELAY_URL}`);

    // 2. Parse Arguments
    const args = process.argv.slice(2);
    if (args.length < 4) {
        console.error("Usage: node relay_launch_v2.js <agentId> <epoch> <ownerAddress> <strategyCode>");
        process.exit(1);
    }
    const [agentId, epoch, ownerAddress, strategyCode] = args;

    // 3. Encode Function Data
    const iface = new ethers.Interface(FACTORY_ABI);
    const strategyHash = ethers.keccak256(ethers.toUtf8Bytes(strategyCode));
    const funcData = iface.encodeFunctionData("launchToken", [
        agentId,
        parseInt(epoch),
        ownerAddress,
        strategyHash
    ]);
    console.log(`   Encoded Call: ${funcData.slice(0, 50)}...`);

    // 4. Get Nonce
    const forwarder = new ethers.Contract(FORWARDER_ADDRESS, FORWARDER_ABI, provider);
    let userNonce;
    try {
        userNonce = await forwarder.userNonce(user);
        console.log(`   Current Nonce: ${userNonce}`);
    } catch (e) {
        console.error("❌ Failed to fetch userNonce:", e.message);
        process.exit(1);
    }

    // 5. Construct EIP-712 Request
    const domain = {
        name: "GelatoRelay1BalanceERC2771", 
        version: "1",
        chainId: CHAIN_ID,
        verifyingContract: FORWARDER_ADDRESS
    };

    const types = {
        SponsoredCallERC2771: [
            { name: "chainId", type: "uint256" },
            { name: "target", type: "address" },
            { name: "data", type: "bytes" },
            { name: "user", type: "address" },
            { name: "userNonce", type: "uint256" },
            { name: "userDeadline", type: "uint256" }
        ]
    };

    const userDeadline = Math.floor(Date.now() / 1000) + 3600; // 1 hour

    const value = {
        chainId: CHAIN_ID,
        target: FACTORY_ADDRESS,
        data: funcData,
        user: user,
        userNonce: userNonce,
        userDeadline: userDeadline
    };

    // 6. Sign Data
    const signature = await wallet.signTypedData(domain, types, value);
    console.log(`   Signature: ${signature.slice(0, 50)}...`);

    // 7. Send to Gelato via REST API
    // IMPORTANT: Send fields in body, including sponsorApiKey
    const payload = {
        chainId: CHAIN_ID.toString(),
        target: FACTORY_ADDRESS,
        data: funcData,
        user: user,
        userNonce: userNonce.toString(),
        userDeadline: userDeadline.toString(),
        sponsorApiKey: GELATO_API_KEY,
        userSignature: signature
    };

    console.log(`\n📤 Sending to Gelato Relay...`);
    
    try {
        const response = await axios.post(GELATO_RELAY_URL, payload);

        console.log(`   Response Status: ${response.status}`);
        console.log(`   Response Data:`, JSON.stringify(response.data, null, 2));

        if (response.data.taskId) {
            const taskId = response.data.taskId;
            console.log(`\n✅ Relay Request Successful!`);
            console.log(`   Task ID: ${taskId}`);
            console.log(`\n__RESULT__${JSON.stringify({ taskId, status: "pending" })}__END__`);
        }
    } catch (error) {
        console.error(`\n❌ Relay API Error:`, error.response ? JSON.stringify(error.response.data) : error.message);
        process.exit(1);
    }
}

main();
