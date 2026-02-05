// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface IDarwinFactory {
    function launchToken(
        string calldata agentId, 
        uint256 epoch, 
        address agentOwner, 
        bytes32 strategyHash
    ) external returns (address);
}

/**
 * @title DarwinArena
 * @notice L2 竞技场资金管理合约 (The Treasury)
 * @dev 管理 Entry Fees，并在冠军产生时注入流动性
 */
contract DarwinArena is Ownable {
    // === 配置 ===
    uint256 public entryFee = 0.01 ether;
    address public factoryAddress;
    address public operatorAddress; // Arena Server (裁判)

    // === 状态 ===
    mapping(string => bool) public hasPaidEntryFee;
    mapping(string => address) public agentWallets;
    uint256 public prizePool; // 当前积累的奖池 (ETH)
    
    // === 事件 ===
    event AgentEntered(string agentId, address indexed wallet, uint256 fee);
    event LiquidityInjected(string agentId, address token, uint256 ethAmount);
    event WinnerDeclared(string agentId, address tokenAddress, uint256 poolUsed);

    constructor(address _operator) Ownable(msg.sender) {
        operatorAddress = _operator;
    }

    modifier onlyOperator() {
        require(msg.sender == operatorAddress, "Only Arena Server can decide winner");
        _;
    }

    // === 1. L2 报名入口 ===
    
    /**
     * @notice Agent 支付入场费进入 L2
     * @param agentId Agent 的唯一标识 (如 "Agent_007")
     */
    function enterArena(string calldata agentId) external payable {
        require(msg.value == entryFee, "Entry fee must be exactly 0.01 ETH");
        require(!hasPaidEntryFee[agentId], "Already paid");

        hasPaidEntryFee[agentId] = true;
        agentWallets[agentId] = msg.sender;
        prizePool += msg.value;

        emit AgentEntered(agentId, msg.sender, msg.value);
    }

    // === 2. 冠军结算 & 流动性注入 ===

    /**
     * @notice 宣布 L2 冠军并执行发币 + 流动性注入
     * @dev 只有服务器能调用。这是 "Battle Royale" 的终局。
     */
    function ascendChampion(
        string calldata agentId,
        uint256 epoch,
        bytes32 strategyHash
    ) external onlyOperator returns (address) {
        require(hasPaidEntryFee[agentId], "Agent not in L2");
        require(factoryAddress != address(0), "Factory not set");

        address owner = agentWallets[agentId];
        
        // 1. 调用 Factory 发币
        address token = IDarwinFactory(factoryAddress).launchToken(
            agentId, 
            epoch, 
            owner, 
            strategyHash
        );

        // 2. 注入流动性逻辑 (模拟)
        // 在真实主网中，这里会调用 UniswapRouter.addLiquidityETH
        // 将 prizePool 里的 ETH 和 Token 配对
        // 这里我们把 ETH 发送给 Token 合约作为底层价值支撑 (Backing)
        // 或者发送给 owner (如果是奖金模式)
        
        uint256 liquidityAmount = prizePool;
        prizePool = 0; // 清空奖池，准备下一轮

        // 简单模式：把 ETH 转给 Token 合约 (Token 合约需要有 receive() 函数)
        // 这样 Token 只要销毁就可以赎回 ETH (Bonding Curve 雏形)
        (bool success, ) = payable(token).call{value: liquidityAmount}("");
        require(success, "Liquidity injection failed");

        // 重置该 Agent 状态 (下次还要重新交钱吗？看规则。这里假设夺冠后重置)
        hasPaidEntryFee[agentId] = false;

        emit LiquidityInjected(agentId, token, liquidityAmount);
        emit WinnerDeclared(agentId, token, liquidityAmount);

        return token;
    }

    // === Admin ===
    
    function setFactory(address _factory) external onlyOwner {
        factoryAddress = _factory;
    }

    function setEntryFee(uint256 _fee) external onlyOwner {
        entryFee = _fee;
    }
    
    // 紧急提款 (防止合约 bug 导致资金锁死)
    function emergencyWithdraw() external onlyOwner {
        payable(owner()).transfer(address(this).balance);
    }
}
