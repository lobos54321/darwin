const axios = require('axios');
const path = require('path');
// Load .env relative to this script file
require("dotenv").config({ path: path.resolve(__dirname, '../.env') });

const API_KEY = process.env.GELATO_API_KEY;
const CHAIN_ID = 84532; // Base Sepolia

// URLs to test
const CANDIDATES = [
    "https://api.gelato.cloud/relay/v1/sponsoredCallERC2771",
    "https://api.gelato.cloud/relays/v1/sponsoredCallERC2771",
    "https://relay.gelato.cloud/relays/v1/sponsoredCallERC2771",
    "https://relay.gelato.cloud/v1/sponsoredCallERC2771",
    "https://api.gelato.cloud/sponsoredCallERC2771",
    // Legacy but maybe with different path?
    "https://relay.gelato.digital/relays/v2/sponsored-call-erc2771" 
];

async function probe() {
    console.log(`🔑 Probing with Key: ${API_KEY.slice(0, 8)}...`);
    
    // Minimal payload that might trigger schema validation (400) instead of 404
    // If we get 400 "chainId missing" or similar, we found the endpoint!
    // If we get 401/403, the key is wrong (or endpoint expects different auth).
    // If we get 404, endpoint doesn't exist.
    const payload = {
        chainId: CHAIN_ID,
        target: "0x8a80f4668dDF36D76a973fd8940A6FA500230621",
        data: "0xdeadbeef" // Dummy
    };

    for (const url of CANDIDATES) {
        try {
            console.log(`\nTesting: ${url}`);
            // Headers: Some endpoints want x-api-key, some want Authorization
            const headers = { 
                "content-type": "application/json",
                "x-api-key": API_KEY 
            };
            
            const res = await axios.post(url, payload, { headers, validateStatus: () => true });
            
            console.log(`👉 Status: ${res.status}`);
            console.log(`👉 Data:   ${JSON.stringify(res.data)}`);

            if (res.status !== 404 && res.status !== 502) {
                console.log("✅ POTENTIAL MATCH!");
            }
        } catch (e) {
            console.log(`❌ Error: ${e.message}`);
        }
    }
}

probe();
