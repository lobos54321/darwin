// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title DarwinToken
 * @notice 冠军 Agent 代币 - 由 Darwin Factory 部署
 * @dev 包含交易税机制
 */
contract DarwinToken is ERC20, Ownable {
    // 税率 (基点, 1% = 100)
    uint256 public constant PLATFORM_TAX_BPS = 50;  // 0.5%
    uint256 public constant OWNER_TAX_BPS = 50;     // 0.5%
    uint256 public constant BPS_DENOMINATOR = 10000;
    
    // 税收接收地址
    address public platformWallet;
    address public agentOwner;
    
    // Agent 元数据
    string public agentId;
    uint256 public epochWon;
    bytes32 public strategyHash;  // 获胜策略的哈希
    
    // 免税地址 (用于 DEX 流动性等)
    mapping(address => bool) public isTaxExempt;
    
    // 事件
    event TaxCollected(address indexed from, uint256 platformAmount, uint256 ownerAmount);
    
    constructor(
        string memory name_,
        string memory symbol_,
        string memory agentId_,
        uint256 epochWon_,
        bytes32 strategyHash_,
        address platformWallet_,
        address agentOwner_,
        uint256 initialSupply
    ) ERC20(name_, symbol_) Ownable(msg.sender) {
        agentId = agentId_;
        epochWon = epochWon_;
        strategyHash = strategyHash_;
        platformWallet = platformWallet_;
        agentOwner = agentOwner_;
        
        // 铸造初始供应量
        _mint(address(this), initialSupply);
        
        // 部署合约免税
        isTaxExempt[address(this)] = true;
        isTaxExempt[platformWallet_] = true;
    }
    
    /**
     * @notice 重写 transfer 以收取交易税
     */
    function transfer(address to, uint256 amount) public override returns (bool) {
        return _transferWithTax(msg.sender, to, amount);
    }
    
    /**
     * @notice 重写 transferFrom 以收取交易税
     */
    function transferFrom(address from, address to, uint256 amount) public override returns (bool) {
        _spendAllowance(from, msg.sender, amount);
        return _transferWithTax(from, to, amount);
    }
    
    /**
     * @dev 带税转账的内部实现
     */
    function _transferWithTax(address from, address to, uint256 amount) internal returns (bool) {
        // 如果发送方或接收方免税，则不收税
        if (isTaxExempt[from] || isTaxExempt[to]) {
            _transfer(from, to, amount);
            return true;
        }
        
        // 计算税额
        uint256 platformTax = (amount * PLATFORM_TAX_BPS) / BPS_DENOMINATOR;
        uint256 ownerTax = (amount * OWNER_TAX_BPS) / BPS_DENOMINATOR;
        uint256 totalTax = platformTax + ownerTax;
        uint256 amountAfterTax = amount - totalTax;
        
        // 执行转账
        _transfer(from, platformWallet, platformTax);
        _transfer(from, agentOwner, ownerTax);
        _transfer(from, to, amountAfterTax);
        
        emit TaxCollected(from, platformTax, ownerTax);
        
        return true;
    }
    
    /**
     * @notice 设置免税地址
     */
    function setTaxExempt(address account, bool exempt) external onlyOwner {
        isTaxExempt[account] = exempt;
    }
    
    /**
     * @notice 更新平台钱包
     */
    function setPlatformWallet(address newWallet) external onlyOwner {
        require(newWallet != address(0), "Invalid address");
        platformWallet = newWallet;
    }
}
