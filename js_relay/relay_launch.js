/**
 * Gelato Cloud Turbo Relayer - Sponsored Transaction
 * 无需签名，Gelato 直接执行
 */

const { ethers } = require("ethers");
const axios = require("axios");

// 配置
const GELATO_API_KEY = process.env.GELATO_API_KEY;
const FACTORY_ADDRESS = process.env.FACTORY_ADDRESS || "0x8a80f4668dDF36D76a973fd8940A6FA500230621";
const CHAIN_ID = "84532"; // 必须是 string

// Gelato Cloud API
const GELATO_RPC_URL = "https://api.gelato.cloud/rpc";

const FACTORY_ABI = [
  "function launchToken(string agentId, uint256 epoch, address agentOwner, bytes32 strategyHash) external returns (address)"
];

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 4) {
    console.error("Usage: node relay_launch.js <agentId> <epoch> <ownerAddress> <strategyCode>");
    process.exit(1);
  }

  const [agentId, epoch, ownerAddress, strategyCode] = args;
  
  console.log("============================================================");
  console.log("🚀 Gelato Cloud Turbo Relayer (Sponsored)");
  console.log("============================================================");
  console.log(`  Agent: ${agentId}`);
  console.log(`  Epoch: ${epoch}`);
  console.log(`  Owner: ${ownerAddress}`);
  console.log(`  Target: ${FACTORY_ADDRESS}`);
  console.log(`  Chain: ${CHAIN_ID} (Base Sepolia)`);
  console.log(`  API Key: ${GELATO_API_KEY?.slice(0, 15)}...`);

  // 编码合约调用
  const iface = new ethers.Interface(FACTORY_ABI);
  const strategyHash = ethers.keccak256(ethers.toUtf8Bytes(strategyCode));
  const data = iface.encodeFunctionData("launchToken", [
    agentId,
    parseInt(epoch),
    ownerAddress,
    strategyHash
  ]);

  console.log(`\n📝 Encoded data: ${data.slice(0, 66)}...`);

  // 构建 JSON-RPC 请求 - params 是 object 不是 array
  const payload = {
    id: 1,
    jsonrpc: "2.0",
    method: "relayer_sendTransaction",
    params: {
      chainId: CHAIN_ID,
      to: FACTORY_ADDRESS,
      data: data,
      payment: {
        type: "sponsored"
      }
    }
  };

  console.log("\n🔄 Sending to Gelato Cloud API...");
  console.log("   Payload:", JSON.stringify(payload, null, 2));

  try {
    const response = await axios.post(GELATO_RPC_URL, payload, {
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": GELATO_API_KEY
      }
    });

    console.log(`\n📡 Response:`, JSON.stringify(response.data, null, 2));

    if (response.data.result) {
      const taskId = response.data.result;
      console.log(`\n✅ Task submitted!`);
      console.log(`  Task ID: ${taskId}`);
      console.log(`\n__RESULT__${JSON.stringify({ taskId, status: "pending" })}__END__`);
    } else if (response.data.error) {
      console.error(`\n❌ Error: ${response.data.error.message}`);
      console.error(`   Details:`, JSON.stringify(response.data.error.data));
      process.exit(1);
    }
    
  } catch (error) {
    if (error.response) {
      console.error(`\n❌ API Error (${error.response.status}):`, JSON.stringify(error.response.data));
    } else {
      console.error(`\n❌ Error: ${error.message}`);
    }
    process.exit(1);
  }
}

main();
