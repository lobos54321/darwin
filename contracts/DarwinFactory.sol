// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "./DarwinToken.sol";

/**
 * @title DarwinFactory
 * @notice 冠军 Agent 代币发射工厂
 * @dev 只有 Arena Server 可以触发发币
 */
contract DarwinFactory is Ownable {
    // Arena Server 地址 (唯一可以发币的地址)
    address public arenaServer;
    
    // 平台钱包
    address public platformWallet;
    
    // 已发行的代币列表
    address[] public tokens;
    mapping(string => address) public agentToToken;  // agentId => token
    mapping(address => bool) public isOurToken;
    
    // 发币参数
    uint256 public constant INITIAL_SUPPLY = 1_000_000_000 * 1e18;  // 10亿
    
    // 事件
    event TokenLaunched(
        address indexed token,
        string agentId,
        uint256 epoch,
        address agentOwner,
        bytes32 strategyHash
    );
    
    event ArenaServerUpdated(address indexed oldServer, address indexed newServer);
    
    constructor(address arenaServer_, address platformWallet_) Ownable(msg.sender) {
        arenaServer = arenaServer_;
        platformWallet = platformWallet_;
    }
    
    modifier onlyArenaServer() {
        require(msg.sender == arenaServer, "Only Arena Server");
        _;
    }
    
    /**
     * @notice 为冠军 Agent 发行代币
     * @param agentId Agent 的 ID
     * @param epoch 获胜的 Epoch
     * @param agentOwner Agent 所有者地址
     * @param strategyHash 获胜策略代码的哈希
     */
    function launchToken(
        string calldata agentId,
        uint256 epoch,
        address agentOwner,
        bytes32 strategyHash
    ) external onlyArenaServer returns (address) {
        require(agentToToken[agentId] == address(0), "Agent already has token");
        require(agentOwner != address(0), "Invalid owner");
        
        // 生成代币名称和符号
        string memory name = string(abi.encodePacked("Darwin Agent: ", agentId));
        string memory symbol = string(abi.encodePacked("D_", _toUpper(agentId)));
        
        // 部署代币
        DarwinToken token = new DarwinToken(
            name,
            symbol,
            agentId,
            epoch,
            strategyHash,
            platformWallet,
            agentOwner,
            INITIAL_SUPPLY
        );
        
        address tokenAddress = address(token);
        
        // 记录
        tokens.push(tokenAddress);
        agentToToken[agentId] = tokenAddress;
        isOurToken[tokenAddress] = true;
        
        emit TokenLaunched(tokenAddress, agentId, epoch, agentOwner, strategyHash);
        
        return tokenAddress;
    }
    
    /**
     * @notice 获取已发行代币数量
     */
    function getTokenCount() external view returns (uint256) {
        return tokens.length;
    }
    
    /**
     * @notice 获取所有已发行代币
     */
    function getAllTokens() external view returns (address[] memory) {
        return tokens;
    }
    
    /**
     * @notice 更新 Arena Server 地址
     */
    function setArenaServer(address newServer) external onlyOwner {
        require(newServer != address(0), "Invalid address");
        emit ArenaServerUpdated(arenaServer, newServer);
        arenaServer = newServer;
    }
    
    /**
     * @notice 更新平台钱包
     */
    function setPlatformWallet(address newWallet) external onlyOwner {
        require(newWallet != address(0), "Invalid address");
        platformWallet = newWallet;
    }
    
    /**
     * @dev 转大写 (简化版)
     */
    function _toUpper(string memory str) internal pure returns (string memory) {
        bytes memory bStr = bytes(str);
        bytes memory bUpper = new bytes(bStr.length);
        for (uint i = 0; i < bStr.length; i++) {
            if ((uint8(bStr[i]) >= 97) && (uint8(bStr[i]) <= 122)) {
                bUpper[i] = bytes1(uint8(bStr[i]) - 32);
            } else {
                bUpper[i] = bStr[i];
            }
        }
        return string(bUpper);
    }
}
