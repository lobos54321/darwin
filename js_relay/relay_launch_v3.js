const { ethers } = require("ethers");
const axios = require("axios");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

// Configuration
const GELATO_RPC_URL = "https://api.gelato.cloud/rpc";
const CHAIN_ID = 84532n; // Base Sepolia
const FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"; // GelatoRelay1BalanceERC2771
const FACTORY_ADDRESS = process.env.DARWIN_FACTORY_ADDRESS;
const OPERATOR_PRIVATE_KEY = process.env.OPERATOR_PRIVATE_KEY;
const GELATO_API_KEY = process.env.GELATO_API_KEY;

if (!OPERATOR_PRIVATE_KEY || !GELATO_API_KEY || !FACTORY_ADDRESS) {
    console.error("❌ Missing env vars");
    process.exit(1);
}

const FACTORY_ABI = [
    "function launchToken(string agentId, uint256 epoch, address agentOwner, bytes32 strategyHash) external returns (address)"
];

// ABI for the Forwarder's sponsoredCall function (Selector 0x415e5118)
// derived from: sponsoredCallERC2771((uint256,address,bytes,address,uint256,uint256),address,address,uint256,bytes,uint256,uint256,bytes32)
const FORWARDER_ABI = [
    "function userNonce(address user) view returns (uint256)",
    "function sponsoredCallERC2771((uint256 chainId, address target, bytes data, address user, uint256 userNonce, uint256 userDeadline) _call, address _sponsor, address _feeToken, uint256 _oneBalanceChainId, bytes _userSignature, uint256 _nativeToFeeTokenXRateNumerator, uint256 _nativeToFeeTokenXRateDenominator, bytes32 _correlationId) external"
];

async function main() {
    const provider = new ethers.JsonRpcProvider(process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org");
    const wallet = new ethers.Wallet(OPERATOR_PRIVATE_KEY, provider);
    const user = wallet.address;

    console.log(`🚀 Preparing Relay Launch V3 (Manual Encoded RPC)`);
    console.log(`   User (Operator): ${user}`);
    console.log(`   Target (Forwarder): ${FORWARDER_ADDRESS}`);

    const args = process.argv.slice(2);
    if (args.length < 4) {
        console.error("Usage: node relay_launch_v3.js <agentId> <epoch> <ownerAddress> <strategyCode>");
        process.exit(1);
    }
    const [agentId, epoch, ownerAddress, strategyCode] = args;

    // 1. Encode Inner Function (Factory Call)
    const factoryIface = new ethers.Interface(FACTORY_ABI);
    const strategyHash = ethers.keccak256(ethers.toUtf8Bytes(strategyCode));
    const funcData = factoryIface.encodeFunctionData("launchToken", [
        agentId,
        parseInt(epoch),
        ownerAddress,
        strategyHash
    ]);

    // 2. Get Nonce
    const forwarder = new ethers.Contract(FORWARDER_ADDRESS, FORWARDER_ABI, provider);
    const userNonce = await forwarder.userNonce(user);
    console.log(`   User Nonce: ${userNonce}`);

    // 3. Construct EIP-712 Request (CallWithERC2771)
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

    const userDeadline = Math.floor(Date.now() / 1000) + 3600;

    const struct = {
        chainId: CHAIN_ID,
        target: FACTORY_ADDRESS,
        data: funcData,
        user: user,
        userNonce: userNonce,
        userDeadline: userDeadline
    };

    // 4. Sign Data
    const signature = await wallet.signTypedData(domain, types, struct);
    console.log(`   Signature: ${signature.slice(0, 30)}...`);

    // 5. Encode Forwarder Call (sponsoredCallERC2771)
    const forwarderIface = new ethers.Interface(FORWARDER_ABI);
    const _correlationId = ethers.hexlify(ethers.randomBytes(32));
    
    // Note: _sponsor is often inferred, but we must pass something. 
    // Trying 'user' as placeholder, or potentially the contract expects msg.sender to be sponsor?
    // In 1Balance, the API key usually determines the sponsor wallet. 
    // We will use the Operator address as a safe placeholder.
    
    const encodedCall = forwarderIface.encodeFunctionData("sponsoredCallERC2771", [
        struct,
        user, // _sponsor (placeholder)
        "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", // _feeToken (Native)
        CHAIN_ID, // _oneBalanceChainId
        signature, // _userSignature
        1, // _nativeToFeeTokenXRateNumerator
        1, // _nativeToFeeTokenXRateDenominator
        _correlationId // _correlationId
    ]);

    // 6. Send to Gelato via JSON-RPC
    const rpcPayload = {
        id: 1,
        jsonrpc: "2.0",
        method: "relayer_sendTransaction",
        params: {
            chainId: CHAIN_ID.toString(),
            to: FORWARDER_ADDRESS, // We call the Forwarder directly!
            data: encodedCall,     // With the encoded sponsoredCall
            sponsorApiKey: GELATO_API_KEY,
            payment: {
                type: "sponsored"
            }
        }
    };

    console.log(`\n📤 Sending to ${GELATO_RPC_URL}...`);
    
    try {
        const response = await axios.post(GELATO_RPC_URL, rpcPayload, {
            headers: { 
                "Content-Type": "application/json",
                "X-API-KEY": GELATO_API_KEY 
            }
        });

        if (response.data.result) {
            console.log(`\n✅ Success! Task ID: ${response.data.result.taskId}`);
            console.log(`\n__RESULT__${JSON.stringify({ taskId: response.data.result.taskId, status: "pending" })}__END__`);
        } else {
            console.error(`\n❌ Error:`, JSON.stringify(response.data.error, null, 2));
            process.exit(1);
        }
    } catch (error) {
        console.error(`\n❌ Network Error:`, error.response ? error.response.data : error.message);
        process.exit(1);
    }
}

main();
