// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title BondingCurve
 * @notice 联合曲线 - 用于冠军代币的初始定价和流动性
 * @dev 类似 pump.fun 的机制
 */
contract BondingCurve is Ownable, ReentrancyGuard {
    // 曲线参数
    uint256 public constant CURVE_EXPONENT = 2;  // 二次曲线
    uint256 public constant INITIAL_PRICE = 0.0001 ether;  // 初始价格
    uint256 public constant PRICE_INCREMENT = 0.00001 ether;  // 每单位增量
    
    // 毕业阈值 (达到后迁移到 Uniswap)
    uint256 public constant GRADUATION_MARKET_CAP = 30000 * 1e18;  // $30k
    
    // 代币和状态
    IERC20 public token;
    bool public graduated;
    uint256 public totalSold;
    uint256 public ethCollected;
    
    // 事件
    event Buy(address indexed buyer, uint256 ethIn, uint256 tokensOut, uint256 newPrice);
    event Sell(address indexed seller, uint256 tokensIn, uint256 ethOut, uint256 newPrice);
    event Graduated(uint256 marketCap, uint256 liquidity);
    
    constructor(address token_) Ownable(msg.sender) {
        token = IERC20(token_);
    }
    
    /**
     * @notice 获取当前价格 (基于已售出数量)
     */
    function getCurrentPrice() public view returns (uint256) {
        return INITIAL_PRICE + (totalSold * PRICE_INCREMENT / 1e18);
    }
    
    /**
     * @notice 计算买入可获得的代币数量
     */
    function calculateBuyReturn(uint256 ethAmount) public view returns (uint256) {
        uint256 price = getCurrentPrice();
        // 简化计算: tokens = eth / price
        // 实际应该用积分计算曲线下面积
        return (ethAmount * 1e18) / price;
    }
    
    /**
     * @notice 计算卖出可获得的 ETH 数量
     */
    function calculateSellReturn(uint256 tokenAmount) public view returns (uint256) {
        uint256 price = getCurrentPrice();
        // 简化计算: eth = tokens * price * 0.95 (5% 滑点保护)
        return (tokenAmount * price * 95) / (100 * 1e18);
    }
    
    /**
     * @notice 买入代币
     */
    function buy() external payable nonReentrant {
        require(!graduated, "Curve graduated");
        require(msg.value > 0, "No ETH sent");
        
        uint256 tokensOut = calculateBuyReturn(msg.value);
        require(token.balanceOf(address(this)) >= tokensOut, "Insufficient tokens");
        
        // 更新状态
        totalSold += tokensOut;
        ethCollected += msg.value;
        
        // 转移代币
        token.transfer(msg.sender, tokensOut);
        
        emit Buy(msg.sender, msg.value, tokensOut, getCurrentPrice());
        
        // 检查是否毕业
        _checkGraduation();
    }
    
    /**
     * @notice 卖出代币
     */
    function sell(uint256 tokenAmount) external nonReentrant {
        require(!graduated, "Curve graduated");
        require(tokenAmount > 0, "No tokens");
        require(token.balanceOf(msg.sender) >= tokenAmount, "Insufficient balance");
        
        uint256 ethOut = calculateSellReturn(tokenAmount);
        require(address(this).balance >= ethOut, "Insufficient ETH");
        
        // 更新状态
        totalSold -= tokenAmount;
        ethCollected -= ethOut;
        
        // 转移代币和 ETH
        token.transferFrom(msg.sender, address(this), tokenAmount);
        payable(msg.sender).transfer(ethOut);
        
        emit Sell(msg.sender, tokenAmount, ethOut, getCurrentPrice());
    }
    
    /**
     * @notice 获取当前市值
     */
    function getMarketCap() public view returns (uint256) {
        uint256 price = getCurrentPrice();
        uint256 totalSupply = token.totalSupply();
        return (price * totalSupply) / 1e18;
    }
    
    /**
     * @dev 检查是否达到毕业条件
     */
    function _checkGraduation() internal {
        if (getMarketCap() >= GRADUATION_MARKET_CAP) {
            graduated = true;
            emit Graduated(getMarketCap(), ethCollected);
            // TODO: 自动迁移到 Uniswap V3
            // 这需要与 Uniswap Router 交互，暂时留空
        }
    }
    
    /**
     * @notice 紧急提取 (仅限 owner)
     */
    function emergencyWithdraw() external onlyOwner {
        require(graduated, "Not graduated");
        payable(owner()).transfer(address(this).balance);
    }
    
    receive() external payable {
        // 接收 ETH
    }
}
