#!/usr/bin/env node
/**
 * 转账脚本：从 Bo 的钱包转 ETH 到 Operator
 * 
 * 用法：
 * export PRIVATE_KEY=0x你的私钥
 * node transfer_to_operator.js
 */

const { ethers } = require("ethers");

const OPERATOR_ADDRESS = "0x70B221f73De34C314BD186C19de78E9929aefE7C";
const AMOUNT = "0.02"; // ETH

async function main() {
  const privateKey = process.env.PRIVATE_KEY;
  if (!privateKey) {
    console.error("❌ 请设置 PRIVATE_KEY 环境变量");
    console.log("   export PRIVATE_KEY=0x你的私钥");
    process.exit(1);
  }

  const provider = new ethers.JsonRpcProvider("https://sepolia.base.org");
  const wallet = new ethers.Wallet(privateKey, provider);

  console.log("============================================================");
  console.log("💸 Transfer ETH to Operator");
  console.log("============================================================");
  console.log(`  From: ${wallet.address}`);
  console.log(`  To: ${OPERATOR_ADDRESS}`);
  console.log(`  Amount: ${AMOUNT} ETH`);

  const balance = await provider.getBalance(wallet.address);
  console.log(`  Your balance: ${ethers.formatEther(balance)} ETH`);

  if (balance < ethers.parseEther(AMOUNT)) {
    console.error("❌ 余额不足!");
    process.exit(1);
  }

  console.log("\n🔄 Sending transaction...");
  
  const tx = await wallet.sendTransaction({
    to: OPERATOR_ADDRESS,
    value: ethers.parseEther(AMOUNT)
  });

  console.log(`  Tx Hash: ${tx.hash}`);
  console.log("⏳ Waiting for confirmation...");
  
  const receipt = await tx.wait();
  console.log(`\n✅ Transfer complete!`);
  console.log(`  Block: ${receipt.blockNumber}`);
  console.log(`  Gas Used: ${receipt.gasUsed}`);

  const newBalance = await provider.getBalance(OPERATOR_ADDRESS);
  console.log(`\n  Operator new balance: ${ethers.formatEther(newBalance)} ETH`);
}

main().catch(console.error);
