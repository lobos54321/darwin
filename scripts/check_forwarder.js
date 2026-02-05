const { ethers } = require("ethers");
require('dotenv').config({ path: '/Users/boliu/darwin-workspace/project-darwin/.env' });

const FACTORY_ADDRESS = process.env.DARWIN_FACTORY_ADDRESS;
const RPC_URL = "https://sepolia.base.org";

const ABI = [
  "function isTrustedForwarder(address forwarder) view returns (bool)"
];

const GELATO_FORWARDER = "0xd8253782c45a12053594b9deB72d8e8aB2Fca54c";

async function check() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const contract = new ethers.Contract(FACTORY_ADDRESS, ABI, provider);
  
  try {
    const isTrusted = await contract.isTrustedForwarder(GELATO_FORWARDER);
    console.log(`Is ${GELATO_FORWARDER} trusted? ${isTrusted}`);
  } catch (e) {
    console.error("Error:", e);
  }
}

check();
