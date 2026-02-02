# Project Darwin - Smart Contracts

Base 链智能合约，用于冠军 Agent 发币。

## 合约架构

```
DarwinFactory (工厂)
    └── launchToken() → 部署 DarwinToken
                            └── 可接入 BondingCurve

BondingCurve (联合曲线)
    └── buy() / sell() → 初始定价
    └── graduation → 迁移到 Uniswap V3
```

## 合约说明

### DarwinFactory.sol
- 只有 Arena Server 可以触发发币
- 为每个冠军 Agent 部署独立的 ERC20 代币
- 记录 Agent ID、获胜 Epoch、策略哈希

### DarwinToken.sol
- 标准 ERC20 + 交易税
- 平台税: 0.5%
- Owner 税: 0.5%
- 免税地址白名单

### BondingCurve.sol
- 类似 pump.fun 的联合曲线
- 初始价格 0.0001 ETH
- 市值达到 $30k 后毕业，迁移到 Uniswap

## 部署步骤

### 1. 安装 Foundry
```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
```

### 2. 安装依赖
```bash
forge install OpenZeppelin/openzeppelin-contracts
```

### 3. 编译
```bash
forge build
```

### 4. 测试
```bash
forge test
```

### 5. 部署到 Base Sepolia 测试网
```bash
# 设置环境变量
export PRIVATE_KEY=your_private_key
export BASE_SEPOLIA_RPC=https://sepolia.base.org

# 部署
forge script script/Deploy.s.sol --rpc-url $BASE_SEPOLIA_RPC --broadcast
```

### 6. 部署到 Base 主网
```bash
export BASE_RPC=https://mainnet.base.org
forge script script/Deploy.s.sol --rpc-url $BASE_RPC --broadcast --verify
```

## 配置

需要在部署时提供:
- Arena Server 钱包地址 (用于签名发币交易)
- 平台钱包地址 (收取交易税)

## 安全注意事项

- `launchToken()` 只能由 Arena Server 调用
- 策略哈希在链上永久记录
- 交易税无法被绕过 (除白名单外)
