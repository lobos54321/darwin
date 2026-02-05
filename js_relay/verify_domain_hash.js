const { ethers } = require("ethers");

const TARGET_HASH = "0xfdb15942bfe11d2bacaf23218d54ecea78afb09e835c452e9ad71290cae06b03";
const CHAIN_ID = 84532n;
const VERIFYING_CONTRACT = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";

async function main() {
    const candidates = [
        { name: "GelatoRelayERC2771", version: "1" },
        { name: "GelatoRelay", version: "1" },
        { name: "GelatoRelayERC2771", version: "2" },
        { name: "GelatoRelay", version: "2" }
    ];

    console.log(`Target Hash: ${TARGET_HASH}`);

    for (const c of candidates) {
        const domain = {
            name: c.name,
            version: c.version,
            chainId: CHAIN_ID,
            verifyingContract: VERIFYING_CONTRACT
        };

        const hash = ethers.TypedDataEncoder.hashDomain(domain);
        console.log(`Testing ${c.name} v${c.version}: ${hash}`);
        
        if (hash.toLowerCase() === TARGET_HASH.toLowerCase()) {
            console.log(`\n✅ MATCH FOUND!`);
            console.log(JSON.stringify(domain, null, 2));
            return;
        }
    }
    console.log("\n❌ No match found.");
}

main();
