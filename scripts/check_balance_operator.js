const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

async function main() {
    const provider = new ethers.JsonRpcProvider(process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org");
    const wallet = new ethers.Wallet(process.env.OPERATOR_PRIVATE_KEY, provider);
    
    console.log(`Checking balance for: ${wallet.address}`);
    const balance = await provider.getBalance(wallet.address);
    console.log(`Balance: ${ethers.formatEther(balance)} ETH`);
}

main();
