const { ethers } = require("ethers");
require("dotenv").config({ path: "../.env" });

async function main() {
    // Configuration
    const rpcUrl = "https://sepolia.base.org";
    const privateKey = process.env.DARWIN_PRIVATE_KEY; // Platform Wallet Key
    const operatorAddress = "0x70B221f73De34C314BD186C19de78E9929aefE7C";
    const amountToSend = "0.01"; // ETH

    if (!privateKey) {
        console.error("❌ DARWIN_PRIVATE_KEY not found in .env");
        process.exit(1);
    }

    // Connect
    const provider = new ethers.JsonRpcProvider(rpcUrl);
    const wallet = new ethers.Wallet(privateKey, provider);

    console.log(`Resource: Platform Wallet (${wallet.address})`);
    console.log(`Target:   Operator Wallet (${operatorAddress})`);
    
    // Check Balance
    const balance = await provider.getBalance(wallet.address);
    console.log(`Balance:  ${ethers.formatEther(balance)} ETH`);

    if (balance < ethers.parseEther(amountToSend)) {
        console.error("❌ Insufficient funds");
        process.exit(1);
    }

    // Send Transaction
    console.log(`\n💸 Sending ${amountToSend} ETH...`);
    const tx = await wallet.sendTransaction({
        to: operatorAddress,
        value: ethers.parseEther(amountToSend)
    });

    console.log(`✅ Tx Sent: ${tx.hash}`);
    console.log("⏳ Waiting for confirmation...");
    
    await tx.wait();
    console.log("🎉 Transfer Complete!");
}

main().catch(console.error);
