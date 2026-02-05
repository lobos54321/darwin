// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/metatx/ERC2771Context.sol";
import "./DarwinToken.sol";

/**
 * @title DarwinFactory
 * @notice 冠军 Agent 代币发射工厂
 * @dev 支持 ERC2771 Meta-Transaction + 贡献者空投
 */
contract DarwinFactory is Ownable, ERC2771Context {
    // Arena Server 地址 (Operator Address，只用于签名验证)
    address public arenaServer;
    // L2 竞技场合约 (Treasury) - 也有权限发币
    address public arenaContract;
    
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
    
    event ContributorsRewarded(
        address indexed token,
        uint256 contributorCount,
        uint256 totalScore
    );
    
    event ArenaServerUpdated(address indexed oldServer, address indexed newServer);
    event ArenaContractUpdated(address indexed oldContract, address indexed newContract);
    
    /**
     * @param arenaServer_ Operator 地址 (服务器生成的空钱包)
     * @param platformWallet_ 平台手续费接收地址
     * @param trustedForwarder_ Gelato Relay 的信任转发器地址
     */
    constructor(
        address arenaServer_, 
        address platformWallet_,
        address trustedForwarder_
    ) Ownable(msg.sender) ERC2771Context(trustedForwarder_) {
        arenaServer = arenaServer_;
        platformWallet = platformWallet_;
    }
    
    modifier onlyArenaServer() {
        address sender = _msgSender();
        require(sender == arenaServer || sender == arenaContract, "Only Arena Server or Contract");
        _;
    }
    
    /**
     * @notice 为冠军 Agent 发行代币（简化版，不含贡献者空投）
     */
    function launchToken(
        string calldata agentId,
        uint256 epoch,
        address agentOwner,
        bytes32 strategyHash
    ) external onlyArenaServer returns (address) {
        return _launchToken(agentId, epoch, agentOwner, strategyHash);
    }
    
    /**
     * @notice 为冠军 Agent 发行代币 + 贡献者空投
     * @param agentId Agent 唯一标识
     * @param epoch 获胜的 Epoch
     * @param agentOwner Agent 拥有者地址
     * @param strategyHash 获胜策略的哈希
     * @param contributors 议事厅贡献者钱包地址
     * @param scores 对应的贡献分数
     */
    function launchTokenWithContributors(
        string calldata agentId,
        uint256 epoch,
        address agentOwner,
        bytes32 strategyHash,
        address[] calldata contributors,
        uint256[] calldata scores
    ) external onlyArenaServer returns (address) {
        address tokenAddress = _launchToken(agentId, epoch, agentOwner, strategyHash);
        
        // 执行贡献者空投
        if (contributors.length > 0) {
            DarwinToken token = DarwinToken(tokenAddress);
            token.executeContributorAirdrop(contributors, scores);
            
            uint256 totalScore = 0;
            for (uint i = 0; i < scores.length; i++) {
                totalScore += scores[i];
            }
            
            emit ContributorsRewarded(tokenAddress, contributors.length, totalScore);
        }
        
        return tokenAddress;
    }
    
    /**
     * @dev 内部发币逻辑
     */
    function _launchToken(
        string calldata agentId,
        uint256 epoch,
        address agentOwner,
        bytes32 strategyHash
    ) internal returns (address) {
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
    
    // --- ERC2771 Overrides ---
    
    function _msgSender() internal view override(Context, ERC2771Context) returns (address) {
        return ERC2771Context._msgSender();
    }

    function _msgData() internal view override(Context, ERC2771Context) returns (bytes calldata) {
        return ERC2771Context._msgData();
    }

    function _contextSuffixLength() internal view override(Context, ERC2771Context) returns (uint256) {
        return ERC2771Context._contextSuffixLength();
    }
    
    // --- View Functions ---

    function getTokenCount() external view returns (uint256) {
        return tokens.length;
    }
    
    function getAllTokens() external view returns (address[] memory) {
        return tokens;
    }
    
    // --- Admin Functions ---

    function setArenaServer(address newServer) external onlyOwner {
        require(newServer != address(0), "Invalid address");
        emit ArenaServerUpdated(arenaServer, newServer);
        arenaServer = newServer;
    }

    function setArenaContract(address newContract) external onlyOwner {
        require(newContract != address(0), "Invalid address");
        emit ArenaContractUpdated(arenaContract, newContract);
        arenaContract = newContract;
    }
    
    function setPlatformWallet(address newWallet) external onlyOwner {
        require(newWallet != address(0), "Invalid address");
        platformWallet = newWallet;
    }
    
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
