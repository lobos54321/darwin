// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title DarwinToken
 * @notice 冠军 Agent 代币 (Battle Royale Model)
 * @dev 包含交易税 + 贡献者空投 + 锁仓机制 + ETH Backing
 */
contract DarwinToken is ERC20, Ownable {
    // 税率 (基点, 1% = 100)
    uint256 public constant PLATFORM_TAX_BPS = 50;  // 0.5%
    uint256 public constant OWNER_TAX_BPS = 50;     // 0.5%
    uint256 public constant BPS_DENOMINATOR = 10000;
    
    // === 📊 代币分配 (Darwinonomics v2) ===
    uint256 public constant AGENT_OWNER_SHARE = 2000;     // 20% 给 Agent Owner (减少)
    uint256 public constant PLATFORM_SHARE = 1000;        // 10% 给平台
    uint256 public constant CONTRIBUTOR_SHARE = 3000;     // 30% 给议事厅贡献者 (增加)
    uint256 public constant LIQUIDITY_SHARE = 4000;       // 40% 留给流动性/储备 (大幅增加)
    
    // === 🔒 锁仓时间 ===
    uint256 public constant OWNER_LOCK_DURATION = 30 days;      // Owner 锁 30 天
    uint256 public constant CONTRIBUTOR_LOCK_DURATION = 7 days; // 贡献者 锁 7 天
    
    // 状态变量
    uint256 public launchTime;
    mapping(address => uint256) public lockUntil; // 账户 => 解锁时间戳
    
    // 地址
    address public platformWallet;
    address public agentOwner;
    
    // Agent 元数据
    string public agentId;
    uint256 public epochWon;
    bytes32 public strategyHash;
    
    // 贡献者记录
    bool public airdropExecuted;
    
    // 免税名单
    mapping(address => bool) public isTaxExempt;
    
    // 事件
    event TaxCollected(address indexed from, uint256 platformAmount, uint256 ownerAmount);
    event ContributorAirdrop(address indexed contributor, uint256 amount);
    event TokensBurnedForETH(address indexed user, uint256 tokenAmount, uint256 ethAmount);
    
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
        launchTime = block.timestamp;
        
        // 1. Owner 20% (Locked)
        uint256 ownerAmount = (initialSupply * AGENT_OWNER_SHARE) / BPS_DENOMINATOR;
        _mint(agentOwner_, ownerAmount);
        lockUntil[agentOwner_] = block.timestamp + OWNER_LOCK_DURATION;
        
        // 2. Platform 10%
        uint256 platformAmount = (initialSupply * PLATFORM_SHARE) / BPS_DENOMINATOR;
        _mint(platformWallet_, platformAmount);
        
        // 3. Contract holds 70% (30% Contributors + 40% Liquidity)
        // 贡献者份额稍后由 airdrop 分发，流动性份额永久留在合约支持 burnToRedeem
        uint256 contractAmount = initialSupply - ownerAmount - platformAmount;
        _mint(address(this), contractAmount);
        
        // 免税设置
        isTaxExempt[address(this)] = true;
        isTaxExempt[platformWallet_] = true;
        isTaxExempt[agentOwner_] = true;
    }
    
    /**
     * @notice 执行贡献者空投
     */
    function executeContributorAirdrop(
        address[] calldata _contributors,
        uint256[] calldata _scores
    ) external onlyOwner {
        require(!airdropExecuted, "Airdrop already executed");
        airdropExecuted = true;
        
        uint256 totalScore = 0;
        for (uint i = 0; i < _scores.length; i++) totalScore += _scores[i];
        if (totalScore == 0) return;
        
        // 计算 30% 的具体数量
        uint256 contributorTotal = (totalSupply() * CONTRIBUTOR_SHARE) / BPS_DENOMINATOR;
        uint256 available = balanceOf(address(this));
        // 确保不超过合约余额 (理论上不会，因为合约持有 70%)
        uint256 distributeAmount = contributorTotal < available ? contributorTotal : available;
        
        for (uint i = 0; i < _contributors.length; i++) {
            if (_scores[i] > 0 && _contributors[i] != address(0)) {
                uint256 share = (distributeAmount * _scores[i]) / totalScore;
                if (share > 0) {
                    _transfer(address(this), _contributors[i], share);
                    // 设置锁仓
                    lockUntil[_contributors[i]] = block.timestamp + CONTRIBUTOR_LOCK_DURATION;
                    emit ContributorAirdrop(_contributors[i], share);
                }
            }
        }
    }
    
    // === 核心逻辑: 锁仓控制 ===
    
    /**
     * @notice Hook: 在任何转账前检查锁仓
     */
    function _update(address from, address to, uint256 value) internal override {
        // 检查发送方是否被锁仓
        if (from != address(0) && from != address(this)) { // 忽略 mint 和 burn
            require(block.timestamp >= lockUntil[from], "Token is locked");
        }
        super._update(from, to, value);
    }
    
    // === 核心逻辑: 价值支撑 (Backing) ===
    
    /**
     * @notice 接收 DarwinArena 发来的 ETH 奖池
     */
    receive() external payable {}
    
    /**
     * @notice 销毁代币赎回 ETH (Bonding Curve 退出机制)
     * @dev 只有当合约里有 ETH 时才有效。这是最基础的流动性保证。
     *      价格 = 合约ETH余额 / (总供应量 - 合约持有量)
     *      或者简单点: 按比例赎回储备金
     */
    function burnToRedeem(uint256 tokenAmount) external {
        require(balanceOf(msg.sender) >= tokenAmount, "Insufficient balance");
        require(block.timestamp >= lockUntil[msg.sender], "Token locked");
        
        uint256 ethBalance = address(this).balance;
        require(ethBalance > 0, "No ETH backing");
        
        // 计算可赎回份额
        // 这里的 totalSupply 包含了锁在合约里的 Liquidity Share (40%)
        // 实际上这 40% 应该被视为 "已销毁" 或 "不参与流通"，从而提高每币价值
        // 为了提高价格，我们在分母中减去合约持有的余额
        uint256 circulatingSupply = totalSupply() - balanceOf(address(this)); 
        if (circulatingSupply == 0) circulatingSupply = 1;
        
        // 赎回额 = (销毁数量 / 流通总量) * ETH储备
        uint256 ethToReturn = (tokenAmount * ethBalance) / circulatingSupply;
        
        _burn(msg.sender, tokenAmount);
        payable(msg.sender).transfer(ethToReturn);
        
        emit TokensBurnedForETH(msg.sender, tokenAmount, ethToReturn);
    }
    
    // === 税收逻辑 ===

    function transfer(address to, uint256 amount) public override returns (bool) {
        return _transferWithTax(msg.sender, to, amount);
    }
    
    function transferFrom(address from, address to, uint256 amount) public override returns (bool) {
        _spendAllowance(from, msg.sender, amount);
        return _transferWithTax(from, to, amount);
    }
    
    function _transferWithTax(address from, address to, uint256 amount) internal returns (bool) {
        if (isTaxExempt[from] || isTaxExempt[to]) {
            _transfer(from, to, amount);
            return true;
        }
        
        uint256 platformTax = (amount * PLATFORM_TAX_BPS) / BPS_DENOMINATOR;
        uint256 ownerTax = (amount * OWNER_TAX_BPS) / BPS_DENOMINATOR;
        uint256 amountAfterTax = amount - platformTax - ownerTax;
        
        _transfer(from, platformWallet, platformTax);
        _transfer(from, agentOwner, ownerTax);
        _transfer(from, to, amountAfterTax);
        
        emit TaxCollected(from, platformTax, ownerTax);
        return true;
    }
    
    function setTaxExempt(address account, bool exempt) external onlyOwner {
        isTaxExempt[account] = exempt;
    }
}
