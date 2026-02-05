const axios = require("axios");

const hosts = [
    "https://api.gelato.cloud",
    "https://relay.gelato.cloud",
    "https://relay.gelato.digital", // Old one
    "https://api.gelato.digital"
];

const paths = [
    "/relays/v2/sponsored-call-erc2771",
    "/v2/relays/sponsored-call-erc2771",
    "/v2/sponsored-call-erc2771",
    "/relays/v2/networks" // Check status
];

async function main() {
    console.log("🔍 Probing Gelato API Endpoints...");

    for (const host of hosts) {
        for (const path of paths) {
            const url = `${host}${path}`;
            try {
                // Try a simple GET first (might be 405 Method Not Allowed, which implies existence)
                // Or POST with empty body
                const response = await axios.get(url, { validateStatus: false });
                console.log(`[GET]  ${url} -> ${response.status}`);
                
                // If it's 405 (Method Not Allowed), it likely exists but needs POST
                if (response.status === 405 || response.status === 200) {
                     console.log(`   ✅ POTENTIAL MATCH!`);
                }

            } catch (e) {
                console.log(`[ERR]  ${url} -> ${e.message}`);
            }
        }
    }
}

main();
