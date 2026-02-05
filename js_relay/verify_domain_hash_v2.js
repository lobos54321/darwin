const { ethers } = require("ethers");

const TARGET_HASH = "0xfdb15942bfe11d2bacaf23218d54ecea78afb09e835c452e9ad71290cae06b03";
const CHAIN_ID = 84532n;
const VERIFYING_CONTRACT = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";

async function main() {
    const names = [
        "GelatoRelayERC2771", 
        "GelatoRelay", 
        "GelatoRelay1BalanceERC2771",
        "GelatoRelay1Balance",
        "GelatoOneBalanceRelayERC2771",
        "GelatoOneBalanceRelay"
    ];
    const versions = ["1", "2"];
    const chainIds = [CHAIN_ID, 0n, 1n, 8453n]; // Try mainnet ID too?

    console.log(`Target Hash: ${TARGET_HASH}`);

    for (const name of names) {
        for (const version of versions) {
            for (const cid of chainIds) {
                const domain = {
                    name: name,
                    version: version,
                    chainId: cid,
                    verifyingContract: VERIFYING_CONTRACT
                };

                const hash = ethers.TypedDataEncoder.hashDomain(domain);
                
                if (hash.toLowerCase() === TARGET_HASH.toLowerCase()) {
                    console.log(`\n✅ MATCH FOUND!`);
                    console.log({
                        name: domain.name,
                        version: domain.version,
                        chainId: domain.chainId.toString(),
                        verifyingContract: domain.verifyingContract
                    });
                    console.log(`(ChainId used: ${cid})`);
                    return;
                }
            }
        }
    }
    console.log("\n❌ No match found in expanded search.");
}

main();
