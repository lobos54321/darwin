const { ethers } = require("ethers");
const axios = require("axios");
require("dotenv").config({ path: "../.env" });

// Configuration
const RPC_URL = "https://sepolia.base.org";
const GELATO_RELAY_URL = "https://relay.gelato.digital/relays/v2/sponsored-call-erc2771";
const FORWARDER_ADDRESS = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c"; // GelatoRelay1BalanceERC2771
const FACTORY_ADDRESS = process.env.DARWIN_FACTORY_ADDRESS;
const API_KEY = process.env.GELATO_API_KEY;
const CHAIN_ID = 84532;

// Operator Credentials (Signer)
const OPERATOR_PK = process.env.OPERATOR_PRIVATE_KEY;

if (!OPERATOR_PK || !API_KEY || !FACTORY_ADDRESS) {
    console.error("❌ Missing Config: Check .env for OPERATOR_PRIVATE_KEY, GELATO_API_KEY, DARWIN_FACTORY_ADDRESS");
    process.exit(1);
}

// ABI for Forwarder (to get nonce)
const FORWARDER_ABI = [
    "function userNonce(address account) external view returns (uint256)"
];

// ABI for Factory (to encode function call)
const FACTORY_ABI = [
    "function launchToken(string agentId, uint256 epoch, address agentOwner, bytes32 strategyHash) external returns (address)"
];

async function main() {
    console.log("🧬 Preparing Sponsored Launch via Gelato Legacy API...");

    const provider = new ethers.JsonRpcProvider(RPC_URL);
    const wallet = new ethers.Wallet(OPERATOR_PK, provider);
    const forwarder = new ethers.Contract(FORWARDER_ADDRESS, FORWARDER_ABI, provider);
    const factory = new ethers.Contract(FACTORY_ADDRESS, FACTORY_ABI, provider);

    // 1. Get User Nonce
    console.log(`👤 Operator: ${wallet.address}`);
    const nonce = await forwarder.userNonce(wallet.address);
    console.log(`🔢 Nonce:    ${nonce.toString()}`);

    // 2. Encode Function Call
    // Launch Params: Agent "DarwinOrigin", Epoch 1, Owner = Operator, Hash = Random/Empty
    const agentId = "DarwinOrigin";
    const epoch = 1;
    const owner = wallet.address; // Operator owns it initially
    const strategyHash = ethers.keccak256(ethers.toUtf8Bytes("print('hello world')"));
    
    const funcData = factory.interface.encodeFunctionData("launchToken", [
        agentId,
        epoch,
        owner,
        strategyHash
    ]);
    console.log(`📦 Payload Encoded: ${funcData.slice(0, 50)}...`);

    // 3. EIP-712 Signature
    const deadline = Math.floor(Date.now() / 1000) + 3600; // 1 hour
    
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

    const value = {
        chainId: CHAIN_ID,
        target: FACTORY_ADDRESS,
        data: funcData,
        user: wallet.address,
        userNonce: parseInt(nonce.toString()), // Try number
        userDeadline: deadline
    };

    console.log("✍️  Signing EIP-712 Typed Data...");
    const signature = await wallet.signTypedData(domain, types, value);
    console.log(`✅ Signature: ${signature.slice(0, 50)}...`);

    // 4. Send to Gelato
    // NOTE: Sending API Key in HEADER, as body auth failed with 403.
    const payload = {
        ...value,
        userSignature: signature
    };
    
    const headers = {
        "content-type": "application/json",
        "x-api-key": API_KEY 
    };

    console.log(`🔑 Key (Header): ${API_KEY ? API_KEY.slice(0, 5) + '...' : 'UNDEFINED'}`);
    console.log(`🚀 Sending to Relay: ${GELATO_RELAY_URL}`);
    try {
        const res = await axios.post(GELATO_RELAY_URL, payload, { headers });
        console.log("\n🎉 SUCCESS! Task ID received:");
        console.log(res.data);
        console.log(`\nCheck status: https://relay.gelato.digital/tasks/status/${res.data.taskId}`);
    } catch (error) {
        console.error("❌ Relay Failed:");
        if (error.response) {
            console.error(`Status: ${error.response.status}`);
            console.error(`Data: ${JSON.stringify(error.response.data, null, 2)}`);
        } else {
            console.error(error.message);
        }
    }
}

main().catch(console.error);
