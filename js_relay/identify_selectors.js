const { ethers } = require("ethers");

async function main() {
  const foundSelectors = [
    '0x3644e515',
    '0x415e5118',
    '0x54fd4d50',
    '0x573ea575',
    '0x06fdde03',
    '0x13523610',
    '0x2e04b8e7'
  ];

  const candidates = [
    // Standard
    "sponsoredCall((uint256,address,bytes,address,uint256,uint256),bytes)",
    "execute((uint256,address,bytes,address,uint256,uint256),bytes)",
    
    // 1Balance variants - "1Balance" might be part of the function name?
    "sponsoredCall1Balance((uint256,address,bytes,address,uint256,uint256),bytes)",
    "sponsoredCallERC2771((uint256,address,bytes,address,uint256,uint256),bytes)",
    "gelatoRelay((uint256,address,bytes,address,uint256,uint256),bytes)",
    "sponsoredCallERC27711Balance((uint256,address,bytes,address,uint256,uint256),bytes)",
    
    // Trying to guess based on hash 0x13523610 and 0x415e5118
    // Maybe with "Relay" in name?
    
    // View functions
    "eip712Domain()",
    "DOMAIN_SEPARATOR()",
    "userNonce(address)",
    "name()",
    "version()",
    "getNonce(address)"
  ];

  console.log("Matching selectors...");

  for (const sig of candidates) {
    const hash = ethers.id(sig).slice(0, 10);
    const match = foundSelectors.find(s => s === hash);
    if (match) {
      console.log(`✅ MATCH: ${match} -> ${sig}`);
    } else {
      // console.log(`   No match: ${hash} (${sig})`);
    }
  }
}

main();
