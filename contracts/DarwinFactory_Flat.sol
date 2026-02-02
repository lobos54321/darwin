// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title DarwinFactory (Remix-Compatible Flat Version)
 * @notice 冠军 Agent 代币发射工厂 - 用于 Base Sepolia 测试
 * @dev 包含所有依赖，可直接在 Remix 部署
 */

// ============ OpenZeppelin Contracts (Flattened) ============

abstract contract Context {
    function _msgSender() internal view virtual returns (address) {
        return msg.sender;
    }
}

abstract contract Ownable is Context {
    address private _owner;
    
    error OwnableUnauthorizedAccount(address account);
    error OwnableInvalidOwner(address owner);
    
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    
    constructor(address initialOwner) {
        if (initialOwner == address(0)) {
            revert OwnableInvalidOwner(address(0));
        }
        _transferOwnership(initialOwner);
    }
    
    modifier onlyOwner() {
        _checkOwner();
        _;
    }
    
    function owner() public view virtual returns (address) {
        return _owner;
    }
    
    function _checkOwner() internal view virtual {
        if (owner() != _msgSender()) {
            revert OwnableUnauthorizedAccount(_msgSender());
        }
    }
    
    function renounceOwnership() public virtual onlyOwner {
        _transferOwnership(address(0));
    }
    
    function transferOwnership(address newOwner) public virtual onlyOwner {
        if (newOwner == address(0)) {
            revert OwnableInvalidOwner(address(0));
        }
        _transferOwnership(newOwner);
    }
    
    function _transferOwnership(address newOwner) internal virtual {
        address oldOwner = _owner;
        _owner = newOwner;
        emit OwnershipTransferred(oldOwner, newOwner);
    }
}

interface IERC20 {
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 value) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

interface IERC20Metadata is IERC20 {
    function name() external view returns (string memory);
    function symbol() external view returns (string memory);
    function decimals() external view returns (uint8);
}

abstract contract ERC20 is Context, IERC20, IERC20Metadata {
    mapping(address => uint256) private _balances;
    mapping(address => mapping(address => uint256)) private _allowances;
    uint256 private _totalSupply;
    string private _name;
    string private _symbol;
    
    constructor(string memory name_, string memory symbol_) {
        _name = name_;
        _symbol = symbol_;
    }
    
    function name() public view virtual returns (string memory) { return _name; }
    function symbol() public view virtual returns (string memory) { return _symbol; }
    function decimals() public view virtual returns (uint8) { return 18; }
    function totalSupply() public view virtual returns (uint256) { return _totalSupply; }
    function balanceOf(address account) public view virtual returns (uint256) { return _balances[account]; }
    
    function transfer(address to, uint256 value) public virtual returns (bool) {
        _transfer(_msgSender(), to, value);
        return true;
    }
    
    function allowance(address owner, address spender) public view virtual returns (uint256) {
        return _allowances[owner][spender];
    }
    
    function approve(address spender, uint256 value) public virtual returns (bool) {
        _approve(_msgSender(), spender, value);
        return true;
    }
    
    function transferFrom(address from, address to, uint256 value) public virtual returns (bool) {
        _spendAllowance(from, _msgSender(), value);
        _transfer(from, to, value);
        return true;
    }
    
    function _transfer(address from, address to, uint256 value) internal virtual {
        require(from != address(0) && to != address(0), "Zero address");
        uint256 fromBalance = _balances[from];
        require(fromBalance >= value, "Insufficient balance");
        _balances[from] = fromBalance - value;
        _balances[to] += value;
        emit Transfer(from, to, value);
    }
    
    function _mint(address account, uint256 value) internal {
        require(account != address(0), "Zero address");
        _totalSupply += value;
        _balances[account] += value;
        emit Transfer(address(0), account, value);
    }
    
    function _approve(address owner, address spender, uint256 value) internal virtual {
        require(owner != address(0) && spender != address(0), "Zero address");
        _allowances[owner][spender] = value;
        emit Approval(owner, spender, value);
    }
    
    function _spendAllowance(address owner, address spender, uint256 value) internal virtual {
        uint256 currentAllowance = allowance(owner, spender);
        if (currentAllowance != type(uint256).max) {
            require(currentAllowance >= value, "Insufficient allowance");
            _approve(owner, spender, currentAllowance - value);
        }
    }
}

// ============ Darwin Contracts ============

contract DarwinToken is ERC20, Ownable {
    uint256 public constant PLATFORM_TAX_BPS = 50;
    uint256 public constant OWNER_TAX_BPS = 50;
    uint256 public constant BPS_DENOMINATOR = 10000;
    
    address public platformWallet;
    address public agentOwner;
    string public agentId;
    uint256 public epochWon;
    bytes32 public strategyHash;
    
    mapping(address => bool) public isTaxExempt;
    
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
        _mint(address(this), initialSupply);
        isTaxExempt[address(this)] = true;
        isTaxExempt[platformWallet_] = true;
    }
    
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

contract DarwinFactory is Ownable {
    address public arenaServer;
    address public platformWallet;
    
    address[] public tokens;
    mapping(string => address) public agentToToken;
    mapping(address => bool) public isOurToken;
    
    uint256 public constant INITIAL_SUPPLY = 1_000_000_000 * 1e18;
    
    event TokenLaunched(
        address indexed token,
        string agentId,
        uint256 epoch,
        address agentOwner,
        bytes32 strategyHash
    );
    
    constructor(address arenaServer_, address platformWallet_) Ownable(msg.sender) {
        arenaServer = arenaServer_;
        platformWallet = platformWallet_;
    }
    
    modifier onlyArenaServer() {
        require(msg.sender == arenaServer, "Only Arena Server");
        _;
    }
    
    function launchToken(
        string calldata agentId,
        uint256 epoch,
        address agentOwner,
        bytes32 strategyHash
    ) external onlyArenaServer returns (address) {
        require(agentToToken[agentId] == address(0), "Agent already has token");
        require(agentOwner != address(0), "Invalid owner");
        
        string memory name = string(abi.encodePacked("Darwin Agent: ", agentId));
        string memory symbol = string(abi.encodePacked("D_", agentId));
        
        DarwinToken token = new DarwinToken(
            name, symbol, agentId, epoch, strategyHash,
            platformWallet, agentOwner, INITIAL_SUPPLY
        );
        
        address tokenAddress = address(token);
        tokens.push(tokenAddress);
        agentToToken[agentId] = tokenAddress;
        isOurToken[tokenAddress] = true;
        
        emit TokenLaunched(tokenAddress, agentId, epoch, agentOwner, strategyHash);
        return tokenAddress;
    }
    
    function getTokenCount() external view returns (uint256) {
        return tokens.length;
    }
    
    function setArenaServer(address newServer) external onlyOwner {
        arenaServer = newServer;
    }
    
    function setPlatformWallet(address newWallet) external onlyOwner {
        platformWallet = newWallet;
    }
    
    // 测试用：允许 owner 也能发币
    function launchTokenAsOwner(
        string calldata agentId,
        uint256 epoch,
        address agentOwner,
        bytes32 strategyHash
    ) external onlyOwner returns (address) {
        require(agentToToken[agentId] == address(0), "Agent already has token");
        
        string memory name = string(abi.encodePacked("Darwin Agent: ", agentId));
        string memory symbol = string(abi.encodePacked("D_", agentId));
        
        DarwinToken token = new DarwinToken(
            name, symbol, agentId, epoch, strategyHash,
            platformWallet, agentOwner, INITIAL_SUPPLY
        );
        
        address tokenAddress = address(token);
        tokens.push(tokenAddress);
        agentToToken[agentId] = tokenAddress;
        isOurToken[tokenAddress] = true;
        
        emit TokenLaunched(tokenAddress, agentId, epoch, agentOwner, strategyHash);
        return tokenAddress;
    }
}
